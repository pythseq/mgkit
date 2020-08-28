"""
Calculates pN/pS values
***********************

This script calculates pN/pS using the data produced by the script
:ref:`snp_parser`. The result table is a CSV file.

Calculate Rank pN/pS
********************

The `rank` command of the script reads SNPs information and calculate for each
element of a specific taxonomic rank (species, genus, family, etc.) its pN/pS.

For example, choosing the rank *genus* a table will be produced, similar to:

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
first column in the gene_id stored in the GFF file and the second is the KO:

    Q7N6F9  K05685
    Q7N6F9  K01242
    G7E4F2  K05625

The `Q7N6F9` gene_id is repeated because it has multiple correspondences to KOs
and this format needs to be selected using the `-2` option of the command.

The default type of table expected by the command is a table with a gene ID as
first column one or more tab separated columns with mappings. The previous
table would look like this:

    Q7N6F9  K05685  K01242
    G7E4F2  K05625

These tables can be created from the original GFF file, assuming that mappings
to KO, EC Numbers are included, with a command line like this::

     edit-gff view -a gene_id -a map_KO final.contigs-a3.gff.gz | \
        tr ',' '\t'

Extracting the KOs (which are comma separated in a MGKit GFF file) and changing
any comma to *tab*. This table can be passed to the script and will make it
possible to calculate the pN/pS for the KOs associated to the genes. Only gene
IDs present in this file have a calculated pN/pS.

Changes
*******

.. versionadded:: 0.5.0
"""


import logging
import click
import pickle
from . import utils
from .. import logger
from mgkit import taxon
from mgkit.snps import conv_func
import mgkit.snps.filter as snp_filter

LOG = logging.getLogger(__name__)


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
              type=click.Choice(taxon.TAXON_RANKS, case_sensitive=False),
              show_default=True)
@click.option('-m', '--min-num', default=2, type=click.IntRange(min=2),
              help='Minimum number of samples with a pN/pS to accept',
              show_default=True)
@click.option('-c', '--min-cov', default=4, type=click.IntRange(min=1),
              help='Minimum coverage for SNPs to be accepted',
              show_default=True)
@click.option('-i', '--taxon_ids', type=click.INT, multiple=True,
              help='Taxon IDs to include', default=(2,), show_default=True)
@click.argument('txt_file', type=click.File('w', lazy=False), default='-')
def gen_rank(verbose, taxonomy, snp_data, rank, min_num, min_cov,
             taxon_ids, txt_file):

    logger.config_log(level=logging.DEBUG if verbose else logging.INFO)

    taxonomy = taxon.Taxonomy(taxonomy)

    LOG.info('Only taxa below %s will be included', ', '.join(taxonomy[taxon_id].s_name for taxon_id in taxon_ids))
    LOG.info('Rank %s and above will be included', rank)

    snp_data = pickle.load(snp_data)

    filters = snp_filter.get_default_filters(taxonomy, min_cov=min_cov,
                                             include_only=taxon_ids)

    pnps = conv_func.get_rank_dataframe(snp_data, taxonomy, min_num=min_num,
                                        rank=rank, filters=filters)

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
              type=click.Choice(taxon.TAXON_RANKS, case_sensitive=False),
              show_default=True)
@click.option('-m', '--min-num', default=2, type=click.IntRange(min=2),
              help='Minimum number of samples with a pN/pS to accept',
              show_default=True)
@click.option('-c', '--min-cov', default=4, type=click.IntRange(min=1),
              help='Minimum coverage for SNPs to be accepted',
              show_default=True)
@click.option('-i', '--taxon_ids', type=click.INT, multiple=True,
              help='Taxon IDs to include', default=(2,), show_default=True)
@click.option('-g', '--gene-map', type=click.File(mode='r', lazy=False),
              help='Dictionary to map *gene_id* to another ID', default=None)
@click.option('-2', '--two-columns', is_flag=True,
              help='gene-map is a two columns table with repeated keys')
@click.option('-p', '--separator', default='\t', show_default=True,
              help='column separator for gene-map file')
@click.argument('txt_file', type=click.File('w', lazy=False), default='-')
def gen_full(verbose, taxonomy, snp_data, rank, min_num, min_cov,
             taxon_ids, gene_map, two_columns, separator, txt_file):

    logger.config_log(level=logging.DEBUG if verbose else logging.INFO)

    if gene_map is not None:
        LOG.info('Reading gene-map')
        if two_columns:
            gene_map = read_gene_map_two_columns(gene_map, separator)
        else:
            gene_map = read_gene_map_default(gene_map, separator)

    taxonomy = taxon.Taxonomy(taxonomy)

    LOG.info('Only taxa below %s will be included', ', '.join(taxonomy[taxon_id].s_name for taxon_id in taxon_ids))
    LOG.info('Rank %s and above will be included', rank)

    snp_data = pickle.load(snp_data)

    filters = snp_filter.get_default_filters(taxonomy, min_cov=min_cov,
                                             include_only=taxon_ids)

    pnps = conv_func.get_gene_taxon_dataframe(
        snp_data, taxonomy, gene_map, min_num=min_num, rank=rank,
        filters=filters)

    pnps.to_csv(txt_file)
