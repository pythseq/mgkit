"""
Calculates pN/pS values
***********************

This script calculates pN/pS using the data produced by the script `vcf`
command. The result table is a CSV file.

Parse VCF Files
***************

The `vcf` command will parse a VCF file to produce the pickle file that is used
to calculate the pN/pS.

Calculate Rank pN/pS
********************

The `rank` command of the script reads SNPs information and calculate for each
element of a specific taxonomic rank (species, genus, family, etc.) its pN/pS.
Another option is the *None* rank, which makes the script use the taxonomic ID
found in the annotations.

For example, choosing the rank *genus* a table will be produced, similar to::

    Prevotella,0.0001,1,1.1,0.4
    Methanobrevibacter,1,0.5,0.6,0.8

A pN/pS value for each genus and sample (4 in this case) will be calculated.

It is important to specify the taxonomic IDs to include in tha calculations. By
default only bacteria are included. To get those values, the taxonomy can be
queried using `taxon-utils get`.

Calculate Gene/Rank pN/pS
*************************

The `full` command create a gene/taxon table of pN/pS, internally is a pandas
MultiIndex DataFrame, written in CSV format after script execution. The
difference with the `rank` is the pN/pS calculation is for each gene/taxon and
by default the `gene_id` from the original GFF file is used (which is stored
in the file generated by `snp_parser`). If other gene IDs needs to be used, a
table file can be provided, which can be passed in two column formats.

The default in MGKit is to use Uniprot gene IDs for the functions, but we may
want to examine the Kegg Orthologs instead. A table can be passed where the
first column in the gene_id stored in the GFF file and the second is the KO::

    Q7N6F9  K05685
    Q7N6F9  K01242
    G7E4F2  K05625

The `Q7N6F9` gene_id is repeated because it has multiple correspondences to KOs
and this format needs to be selected using the `-2` option of the command.

The default type of table expected by the command is a table with a gene ID as
first column one or more tab separated columns with mappings. The previous
table would look like this::

    Q7N6F9  K05685  K01242
    G7E4F2  K05625

These tables can be created from the original GFF file, assuming that mappings
to KO, EC Numbers are included, with a command line like this::

     edit-gff view -a gene_id -a map_KO final.contigs-a3.gff.gz | tr ',' '\t'

Extracting the KOs (which are comma separated in a MGKit GFF file) and changing
any comma to *tab*. This table can be passed to the script and will make it
possible to calculate the pN/pS for the KOs associated to the genes. Only gene
IDs present in this file have a calculated pN/pS.

Normally you combine the all isoforms with the same the *gene_id* to produce a
single pN/pS, but if it's needed, the `-u` option can be used to calculate a
pN/pS for each line in the GFF file.

Changes
*******

.. versionchanged:: 0.5.7
    added *vcf* command to parse VCF files and generate data for the script

.. versionchanged:: 0.5.1
    bug fix

.. versionchanged:: 0.5.1

    * added option to include the lineage as a string
    * added option to use the *uids* from the GFF instead of *gene_id*, this
      does not require the GFF file, they are embedded into the *.pickle* file

.. versionadded:: 0.5.0
"""


import logging
from typing import OrderedDict
import itertools
import click
import pickle
import functools
import vcf
from tqdm import tqdm
from mgkit import taxon
from mgkit.snps import conv_func
import mgkit.snps.mapper
import mgkit.snps.funcs
import mgkit.snps.filter as snp_filter
from ..snps.classes import GeneSNP, SNPType
from ..io import gff, fasta
from . import utils
from ..utils import dictionary
from .. import logger

LOG = logging.getLogger(__name__)

# changing the value for the script to remove subclass as rank
taxon.TAXON_RANKS = tuple(rank for rank in taxon.TAXON_RANKS
                          if not rank.startswith('sub'))


def get_lineage(taxonomy, taxon_id):
    if taxon_id not in taxonomy:
        return taxon_id
    return taxonomy.get_lineage_string(taxon_id, only_ranked=True,
                                       with_last=True, add_rank=True,
                                       sep=';')


@click.group()
@click.version_option()
@utils.cite_option
def main():
    "Main function"
    pass


@main.command('rank', help="""Calculates pN/pS for a taxonomic rank""")
@click.option('-v', '--verbose', is_flag=True)
@click.option('-t', '--taxonomy', type=click.File('rb', lazy=False),
              help="Taxonomy file", required=True)
@click.option('-s', '--snp-data', type=click.File('rb', lazy=False),
              help="SNP data, output of `snp_parser`", required=True)
@click.option('-r', '--rank', default='order', help='Taxonomic rank',
              type=click.Choice(taxon.TAXON_RANKS + ('None',),
                                case_sensitive=False), show_default=True)
@click.option('-m', '--min-num', default=2, type=click.IntRange(min=2),
              help='Minimum number of samples with a pN/pS to accept',
              show_default=True)
@click.option('-c', '--min-cov', default=4, type=click.IntRange(min=1),
              help='Minimum coverage for SNPs to be accepted',
              show_default=True)
@click.option('-i', '--taxon_ids', type=click.INT, multiple=True,
              help='Taxon IDs to include', default=(2,), show_default=True)
@click.option('-u', '--unstack', is_flag=True, show_default=True,
              help='Samples are not in columns but as an array')
@click.option('-l', '--lineage', is_flag=True, show_default=True,
              help='Use lineage string instead of taxon_id')
@click.option('-ps', '--only-ps', is_flag=True, show_default=True,
              help='Only calculate pS values')
@click.option('-pn', '--only-pn', is_flag=True, show_default=True,
              help='Only calculate pN values')
@click.argument('txt_file', type=click.File('w', lazy=False), default='-')
def gen_rank(verbose, taxonomy, snp_data, rank, min_num, min_cov,
             taxon_ids, unstack, lineage, only_ps, only_pn, txt_file):

    logger.config_log(level=logging.DEBUG if verbose else logging.INFO)

    taxonomy = taxon.Taxonomy(taxonomy)

    LOG.info('Only taxa below %s will be included', ', '.join(taxonomy[taxon_id].s_name for taxon_id in taxon_ids))
    LOG.info('Rank "%s" and above will be included', rank)

    snp_data = pickle.load(snp_data)

    filters = snp_filter.get_default_filters(taxonomy, min_cov=min_cov,
                                             include_only=taxon_ids)

    if rank not in taxon.TAXON_RANKS:
        rank = None
    
    if rank is None:
        taxon_func = None
    else:
        taxon_func = functools.partial(
            mgkit.snps.mapper.map_taxon_id_to_rank,
            taxonomy=taxonomy,
            rank=rank
        )
    
    partial_calc = False
    partial_syn = True
    if only_ps or only_pn:
        partial_calc = True
        if only_pn:
            partial_syn = False
        LOG.info('Only "%s" will be calculated ', "pS"  if partial_syn else "pN")

    pnps = mgkit.snps.funcs.combine_sample_snps(snp_data, min_num, filters, index_type='taxon',
                                                taxon_func=taxon_func, partial_calc=partial_calc,
                                                partial_syn=partial_syn)

    if lineage:
        pnps.rename(lambda x: get_lineage(taxonomy, x), inplace=True)

    pnps.index.names = ['taxon']

    if unstack:
        pnps = pnps.unstack()

    pnps.to_csv(txt_file)


def read_gene_map_default(file_handle, separator):

    gene_map = {}

    for line in file_handle:
        fields = line.rstrip().split(separator)
        gene_map[fields[0]] = set(fields[1:])

    return gene_map


def read_gene_map_two_columns(file_handle, separator):

    gene_map = {}

    for line in file_handle:
        key, value = line.rstrip().split(separator)
        try:
            gene_map[key].add(value)
        except KeyError:
            gene_map[key] = set([value])

    return gene_map


@main.command('full', help="""Calculates pN/pS""")
@click.option('-v', '--verbose', is_flag=True)
@click.option('-t', '--taxonomy', type=click.File('rb', lazy=False),
              help="Taxonomy file", required=True)
@click.option('-s', '--snp-data', type=click.File('rb', lazy=False),
              help="SNP data, output of `snp_parser`", required=True)
@click.option('-r', '--rank', default=None, help='Taxonomic rank',
              type=click.Choice(taxon.TAXON_RANKS + ('None',),
                                case_sensitive=False), show_default=True)
@click.option('-m', '--min-num', default=2, type=click.IntRange(min=2),
              help='Minimum number of samples with a pN/pS to accept',
              show_default=True)
@click.option('-c', '--min-cov', default=4, type=click.IntRange(min=1),
              help='Minimum coverage for SNPs to be accepted',
              show_default=True)
@click.option('-i', '--taxon-ids', type=click.INT, multiple=True,
              help='Taxon IDs to include', default=None, show_default=True)
@click.option('-u', '--use-uid', is_flag=True, show_default=True,
              help='Use uids from the GFF file instead of gene_id as genes')
@click.option('-g', '--gene-map', type=click.File(mode='r', lazy=False),
              help='Dictionary to map *gene_id* to another ID', default=None)
@click.option('-2', '--two-columns', is_flag=True,
              help='gene-map is a two columns table with repeated keys')
@click.option('-p', '--separator', default='\t', show_default=True,
              help='column separator for gene-map file')
@click.option('-l', '--lineage', is_flag=True, show_default=True,
              help='Use lineage string instead of taxon_id')
@click.option('-e', '--parquet', is_flag=True, show_default=True, default=False,
              help='Output a Parquet file instead of CSV')
@click.option('-ps', '--only-ps', is_flag=True, show_default=True,
              help='Only calculate pS values')
@click.option('-pn', '--only-pn', is_flag=True, show_default=True,
              help='Only calculate pN values')
@click.argument('output_file', type=click.Path(writable=True), required=True)
def gen_full(verbose, taxonomy, snp_data, rank, min_num, min_cov,
             taxon_ids, use_uid, gene_map, two_columns, separator, lineage,
             parquet, only_ps, only_pn, output_file):

    logger.config_log(level=logging.DEBUG if verbose else logging.INFO)

    if gene_map is not None:
        LOG.info('Reading gene-map')
        if two_columns:
            gene_map = read_gene_map_two_columns(gene_map, separator)
        else:
            gene_map = read_gene_map_default(gene_map, separator)
        
        gene_map = functools.partial(
            mgkit.snps.mapper.map_gene_id,
            gene_map=gene_map
        )

    taxonomy = taxon.Taxonomy(taxonomy)

    if rank is not None:
        LOG.info('Rank "%s" and above will be included', rank)

    snp_data = pickle.load(snp_data)

    if rank not in taxon.TAXON_RANKS:
        rank = None
    
    if rank is None:
        taxon_func = None
    else:
        taxon_func = functools.partial(
            mgkit.snps.mapper.map_taxon_id_to_rank,
            taxonomy=taxonomy,
            rank=rank
        )

    filters = [
        functools.partial(
            snp_filter.filter_genesyn_by_coverage,
            min_cov=min_cov
        )
    ]

    if taxon_ids:
        LOG.info('Only taxa below %s will be included', ', '.join(
            taxonomy[taxon_id].s_name for taxon_id in taxon_ids))
        filters.append(
            functools.partial(
                snp_filter.filter_genesyn_by_taxon_id,
                taxonomy=taxonomy,
                filter_list=taxon_ids,
                exclude=False,
                func=taxon.is_ancestor
            )
        )

    partial_calc = False
    partial_syn = True
    if only_ps or only_pn:
        partial_calc = True
        if only_pn:
            partial_syn = False
        LOG.info('Only "%s" will be calculated ', "pS"  if partial_syn else "pN")

    pnps = mgkit.snps.funcs.combine_sample_snps(snp_data, min_num, filters, gene_func=gene_map,
                                                taxon_func=taxon_func, use_uid=use_uid,
                                                partial_calc=partial_calc, partial_syn=partial_syn)

    if lineage:
        pnps.rename(lambda x:  get_lineage(taxonomy, x), inplace=True)

    pnps.index.names = ['gene', 'taxon']

    if parquet:
        pnps.to_parquet(output_file)
    else:
        pnps.to_csv(output_file)


def init_count_set(annotations, seqs):
    LOG.info("Init data structures")

    samples = list(annotations[0].sample_coverage.keys())

    snp_data = dict(
        (sample, {}) for sample in samples
    )

    for annotation in tqdm(annotations):

        taxon_id = annotation.taxon_id

        uid = annotation.uid

        sample_coverage = annotation.sample_coverage
        annotation.add_exp_syn_count(seqs[annotation.seq_id])

        for sample in sample_coverage:
            snp_data[sample][uid] = GeneSNP(
                uid=uid,
                gene_id=annotation.gene_id,
                taxon_id=taxon_id,
                exp_syn=annotation.exp_syn,
                exp_nonsyn=annotation.exp_nonsyn,
                coverage=sample_coverage[sample],
            )

    return snp_data


def init_count_set_sample_files(annotations, seqs, cov_files):
    """
    .. versionadded:: 0.5.7

    """
    LOG.info("Init data structures")

    snp_data = dict(
        (sample, {}) for sample in cov_files
    )

    annotations = list(itertools.chain(*annotations.values()))

    for annotation in tqdm(annotations, desc="Adding Expected Values"):
        annotation.add_exp_syn_count(seqs[annotation.seq_id])

    for sample, cov_file in tqdm(cov_files.items(), desc='Adding Coverage'):
        cov_info = dict(
            dictionary.text_to_dict(cov_file, value_func=float, skip_empty=True, skip_comment='#')
        )

        for annotation in annotations:

            taxon_id = annotation.taxon_id
            uid = annotation.uid

            snp_data[sample][uid] = GeneSNP(
                uid=uid,
                gene_id=annotation.gene_id,
                taxon_id=taxon_id,
                exp_syn=annotation.exp_syn,
                exp_nonsyn=annotation.exp_nonsyn,
                coverage=cov_info.get(uid, 0.),
            )

    return snp_data

def check_snp_in_set(samples, snp_data, pos, change, annotations, seq):
    """
    Used by :func:`parse_vcf` to check if a SNP

    :param iterable samples: list of samples that contain the SNP
    :param dict snp_data: dictionary from :func:`init_count_set` with per
        sample SNPs information
    """

    for annotation in annotations:
        if pos not in annotation:
            continue

        if annotation.is_syn(seq, pos, change, strict=False):
            snp_type = SNPType.syn
        else:
            snp_type = SNPType.nonsyn

        uid = annotation.uid
        rel_pos = annotation.get_relative_pos(pos)

        for sample in samples:
            snp_data[sample][uid].add_snp(rel_pos, change, snp_type=snp_type)


def parse_vcf(vcf_handle, snp_data, annotations, seqs, min_qual, min_reads, min_freq, 
                sample_ids, num_lines, verbose=True):

    # total number of SNPs accepted
    accepted_snps = 0
    # number of SNPs skipped for low depth
    skip_dp = 0
    # number of SNPs skipped for low allele frequency
    skip_af = 0
    # number of SNPs skipped for low quality
    skip_qual = 0
    # indels
    skip_indels = 0

    for line_no, vcf_record in enumerate(vcf_handle):
        if vcf_record.CHROM not in annotations:
            continue

        if vcf_record.is_indel:
            continue

        if vcf_record.INFO['DP'] < min_reads:
            # not enough reads (depth) for the SNP
            skip_dp += 1
            continue

        if vcf_record.QUAL < min_qual:
            # low quality SNP
            skip_qual += 1
            continue

        alleles_freq = dict(zip(map(str, vcf_record.ALT), vcf_record.aaf))
        # Used to keep track of the presence of an allele on which sample
        alleles_sample = {
            str(allele): set()
            for allele in vcf_record.ALT
        }

        for sample_info in vcf_record.samples:
            # equivalent to GT=. no call was made
            if sample_info.gt_bases is None:
                continue
            # Not considering phases/unphased
            # but we really are looking at haployd
            # stress in documentation and examples
            sample_info_gt = sample_info.gt_bases.replace('!', '/')
            if '/' in sample_info_gt:
                sample_info_gt = sample_info_gt.split('/')
            # Haployd
            else:
                sample_info_gt = [sample_info_gt]

            for change in sample_info_gt:
                # if it's the reference continue
                if change == vcf_record.REF:
                    continue
                allele_freq = alleles_freq.get(change, 0)
                if allele_freq < min_freq:
                    continue
                alleles_sample[change].add(sample_ids[sample_info.sample])

        seq = seqs[vcf_record.CHROM]
        ann_seq = annotations[vcf_record.CHROM]

        for change, samples in alleles_sample.items():
            if not samples:
                continue
            check_snp_in_set(samples, snp_data, vcf_record.POS,
                             change, ann_seq, seq)
            accepted_snps += 1

        if verbose and (line_no % (num_lines) == 0):
            LOG.info(
                "Line %d, SNPs passed %d; skipped for: qual %d, " +
                "depth %d, freq %d, indels %d",
                line_no, accepted_snps, skip_qual, skip_dp, skip_af, skip_indels
            )
    if verbose:
        LOG.info(
            "Finished parsing, SNPs passed %d; skipped for: qual %d, " +
            "depth %d, freq %d, indels %d",
            accepted_snps, skip_qual, skip_dp, skip_af, skip_indels
        )
    return accepted_snps, skip_qual, skip_dp, skip_af, skip_indels


def save_data(output_file, snp_data):
    """
    Pickle data structures to the disk.

    :param str output_file: base name for pickle files
    :param dict snp_data: dictionary from :func:`init_count_set` with per
        sample SNPs information
    """

    LOG.info("Saving sample SNPs to %s", output_file)
    pickle.dump(snp_data, output_file, -1)


@main.command('vcf', help="""parse a VCF file and a GFF file to produce the
                data used for `pnps-gen`
                """)
@click.option('-v', '--verbose', is_flag=True)
@click.option('-ft', '--feature', default='CDS', type=click.STRING,
              show_default=True, help="Feature to use in the GFF file")
@click.option('-g', '--gff-file', type=click.File('rb'), required=True,
              help="GFF file to use")
@click.option('-a', '--fasta-file', type=click.File('rb'), required=True,
              help="Reference file (FASTA) for the GFF")
@click.option('-q', '--min-qual', default=30, type=click.INT, show_default=True,
              help="Minimum quality for SNPs (Phred score)")
@click.option('-f', '--min-freq', default=.01, type=click.FLOAT, show_default=True,
              help="Minimum allele frequency")
@click.option('-r', '--min-reads', default=4, type=click.INT, show_default=True,
              help="Minimum number of reads to accept the SNP")
@click.option('-m', '--sample-ids', multiple=True, default=None,
              type=click.STRING, help='''the ids of the samples used in the analysis,
              must be the same as in the GFF file''')
@click.option('-n', '--num-lines', default=10**5, type=click.INT, show_default=True,
              help="Number of VCF lines after which printing status")
@click.argument('vcf-file', type=click.File('r'), default='-')
@click.argument('output-file', type=click.File('wb'))
def parse_command(verbose, feature, gff_file, fasta_file, min_qual, min_freq,
                  min_reads, sample_ids, num_lines, vcf_file, output_file):

    mgkit.logger.config_log(level=logging.DEBUG if verbose else logging.INFO)

    vcf_handle = vcf.Reader(fsock=vcf_file)

    if len(vcf_handle.samples) != len(sample_ids):
        utils.exit_script("The number of sample names is wrong: VCF ({}) -> Passed ({})".format(
            ','.join(vcf_handle.samples), ','.join(sample_ids)), 1
        )

    # Loads them as list because it's easier to init the data structure
    LOG.info("Reading annotations from GFF File, using feat_type: %s", feature)
    annotations = []
    seq_ids = set()
    test_names = True
    for annotation in gff.parse_gff(gff_file):
        if annotation.feat_type != feature:
            continue
        annotations.append(annotation)
        seq_ids.add(annotation.seq_id)
        # checks if sample names are wrong
        if test_names:
            sample_names_gff = set(annotation.sample_coverage.keys())
            if sample_names_gff != set(sample_ids):
                utils.exit_script("Sample names are wrong: GFF ({}) -> Passed ({})".format(
                    ','.join(sample_names_gff), ','.join(sample_ids)), 2
                )
            else:
                test_names = False

    if set(annotations[0].sample_coverage.keys()) != set(sample_ids):
        utils.exit_script("The number of sample names is wrong: VCF ({}) -> Passed ({})".format(
            ','.join(vcf_handle.samples), ','.join(sample_ids)), 1
        )

    sample_ids = dict(zip(vcf_handle.samples, sample_ids))
    LOG.info("Sample IDs from VCF to GFF: %r", sample_ids)

    seqs = {
        seq_id: seq
        for seq_id, seq in fasta.load_fasta(fasta_file)
        if seq_id in seq_ids
    }

    snp_data = init_count_set(annotations, seqs)

    annotations = gff.group_annotations(
        annotations,
        key_func=lambda x: x.seq_id
    )

    parse_vcf(vcf_handle, snp_data, annotations, seqs,
              min_qual, min_reads, min_freq, sample_ids, num_lines)

    save_data(output_file, snp_data)


@main.command('vcf_alt', help="""parse a VCF file and a GFF file to produce the
                data used for `pnps-gen`, uses file a list for sample coverage
                instead of taking information from the GFF file
                """)
@click.option('-v', '--verbose', is_flag=True)
@click.option('-ft', '--feature', default='CDS', type=click.STRING,
              show_default=True, help="Feature to use in the GFF file")
@click.option('-g', '--gff-file', type=click.File('rb'), required=True,
              help="GFF file to use")
@click.option('-a', '--fasta-file', type=click.File('rb'), required=True,
              help="Reference file (FASTA) for the GFF")
@click.option('-q', '--min-qual', default=30, type=click.INT, show_default=True,
              help="Minimum quality for SNPs (Phred score)")
@click.option('-f', '--min-freq', default=.01, type=click.FLOAT, show_default=True,
              help="Minimum allele frequency")
@click.option('-r', '--min-reads', default=4, type=click.INT, show_default=True,
              help="Minimum number of reads to accept the SNP")
@click.option('-n', '--num-lines', default=10**5, type=click.INT, show_default=True,
              help="Number of VCF lines after which printing status")
@click.option('-l', '--sample-file', type=click.File('r'), required=True,
              help="File with list of coverage files and sample names (TAB separated)")
@click.option('-s', '--file-list', type=click.File('r'), default=None,
              help="File with list of VCF files (one per line)")
@click.option('-u', '--uid-map', type=click.File('r'), default=None,
              help="Only load annotations from a specific map file")
@click.argument('vcf-file', type=click.Path(file_okay=True, readable=True), default='-')
@click.argument('output-file', type=click.File('wb'))
def parse_alt_command(verbose, feature, gff_file, fasta_file, min_qual, min_freq,
                  min_reads, num_lines, sample_file, file_list, uid_map, vcf_file, output_file):

    mgkit.logger.config_log(level=logging.DEBUG if verbose else logging.INFO)

    if file_list is None:
        vcf_handles = [vcf.Reader(fsock=open(vcf_file, 'r'))]
    else:
        vcf_handles = [
            vcf.Reader(fsock=open(line.strip(), 'r'))
            for line in file_list
        ]

    cov_files = OrderedDict()
    for line in sample_file:
        sample_id, cov_file = line.strip().split('\t')
        cov_files[sample_id] = open(cov_file, 'r')

    if len(vcf_handles[0].samples) != len(cov_files):
        utils.exit_script("The number of sample names is wrong: VCF ({}) -> Passed ({})".format(
            ','.join(vcf_handles[0].samples), ','.join(cov_files)), 1
        )
    
    LOG.info("VCF sample ID -> Sample ID")
    sample_ids = dict(zip(vcf_handles[0].samples, cov_files))
    for vcf_sample, sample_id in sample_ids.items():
        LOG.info("%s -> %s", vcf_sample, sample_id)

    if uid_map is not None:
        LOG.info("Loading uid from file %s", uid_map)
        uid_map = set(
            line.strip().split('\t')[0]
            for line in uid_map
        )

    # Loads them as list because it's easier to init the data structure
    LOG.info("Reading annotations from GFF File, using feat_type: %s", feature)
    ann_iterator = gff.parse_gff(gff_file)
    if uid_map is not None:
        ann_iterator = filter(lambda x: x.uid in uid_map, ann_iterator)
    annotations = gff.group_annotations(
        (
            annotation
            for annotation in ann_iterator
            if annotation.feat_type == feature
        ),
        key_func=lambda x: x.seq_id
    )

    seqs = {
        seq_id: seq
        for seq_id, seq in fasta.load_fasta(fasta_file)
        if seq_id in annotations
    }

    snp_data = init_count_set_sample_files(annotations, seqs, cov_files)

    if len(vcf_handles) > 1:
        vcf_handles = tqdm(vcf_handles, desc="Parsing VCF Files")
    
    accepted_snps, skip_qual, skip_dp, skip_af, skip_indels = 0, 0, 0, 0, 0
    for vcf_handle in vcf_handles:
        accepted_snps, skip_qual, skip_dp, skip_af, skip_indels = parse_vcf(
                  vcf_handle, snp_data, annotations, seqs,
                  min_qual, min_reads, min_freq, sample_ids, num_lines,
                  verbose=True if len(vcf_handles) == 1 else False)
        accepted_snps += accepted_snps
        skip_qual += skip_qual
        skip_dp += skip_dp
        skip_af += skip_af
        skip_indels += skip_indels

    if not verbose:
        LOG.info(
            "Finished parsing, SNPs passed %d; skipped for: qual %d, " +
            "depth %d, freq %d, indels %d",
            accepted_snps, skip_qual, skip_dp, skip_af, skip_indels
        )

    save_data(output_file, snp_data)
