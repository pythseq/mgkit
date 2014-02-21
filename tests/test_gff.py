from nose.tools import *
import os.path

base_dir = os.path.dirname(os.path.abspath(__file__))

from mgkit.io import gff
from mgkit.io import fasta

F_HANDLE = None
HMMER_HANDLE = None
AA_SEQS = None
NUC_SEQS = None


def setup_gff():
    global F_HANDLE
    F_HANDLE = open(os.path.join(base_dir, 'test.gff'), 'r')


def setup_hmmer_parse():
    global HMMER_HANDLE
    global AA_SEQS
    global NUC_SEQS
    HMMER_HANDLE = open(os.path.join(base_dir, 'test-hmmer-dom.txt'), 'r')
    AA_SEQS = dict(
        fasta.load_fasta(
            os.path.join(base_dir, 'test-seq-aa.fa')
        )
    )
    NUC_SEQS = dict(
        fasta.load_fasta(
            os.path.join(base_dir, 'test-seq-nuc.fa')
        )
    )


def test_gffattributesdict_init():
    ann1 = gff.GFFAttributesDict(ko_idx='test', cov=3)
    ann2 = gff.GFFAttributesDict()
    ann2.ko_idx = 'test'
    ann2.cov = 3
    eq_(ann1, ann2)


def test_gffattributesdict_setattr():
    ann1 = gff.GFFAttributesDict()
    ann2 = gff.GFFAttributesDict()
    ann1['ko_idx'] = 'test'
    ann1['cov'] = 3
    ann2.ko_idx = 'test'
    ann2.cov = 3
    eq_(ann1, ann2)


def test_gffattributesdict_getattr():
    ann1 = gff.GFFAttributesDict(ko_idx='test', cov=3)
    ann2 = gff.GFFAttributesDict(ko_idx='test', cov=3)
    eq_(ann1['ko_idx'], ann2.ko_idx)


def test_gffattributesdict_hash():
    ann1 = gff.GFFAttributesDict(ko_idx='test', cov=3)
    ann2 = gff.GFFAttributesDict()
    ann2.ko_idx = 'test'
    ann2.cov = 3
    eq_(hash(ann1), hash(ann2))


def test_gffattributesdict_hash2():
    ann1 = gff.GFFAttributesDict(ko_idx='test', cov=3)
    ann2 = gff.GFFAttributesDict()
    ann2.ko_idx = 'test'
    ann2.cov = 3
    ann1.calc_hash()
    ann2.calc_hash()
    eq_(ann1._hash, ann2._hash)


def test_gffattributesdict_hash3():
    ann1 = gff.GFFAttributesDict(ko_idx='test', cov=3)
    ann2 = gff.GFFAttributesDict(ko_idx='test', cov=3)
    ann1.calc_hash()
    ann2.calc_hash()
    ann2['cov'] = 9
    eq_(ann1._hash, ann2._hash)


def test_gffattributesdict_to_string():
    ann1 = gff.GFFAttributesDict(ko_idx='test', cov=3)
    eq_(ann1.to_string(), 'cov="3";ko_idx="test"')


@with_setup(setup=setup_gff)
def test_basegffdict_parse_line():

    line = F_HANDLE.readline()

    ann = gff.BaseGFFDict(line)

    eq_("KMSRIGKLPITVPAGVTVTVDENNLVTVKGPKGTLSQQVNPDITLKQEGNILTLERPTDSKPHKAMHGL",
        ann.attributes.aa_seq)


@with_setup(setup=setup_gff)
def test_basegffdict_parse_line2():

    line = F_HANDLE.readline()

    ann = gff.BaseGFFDict(line)

    eq_(209, ann.feat_to)


@with_setup(setup=setup_gff)
def test_basegffdict_calc_hash():

    line = F_HANDLE.readline()

    ann1 = gff.BaseGFFDict(line)
    ann2 = gff.BaseGFFDict(line)

    eq_(hash(ann1), hash(ann2))


@with_setup(setup=setup_gff)
def test_basegffdict_calc_hash2():

    line1 = F_HANDLE.readline()
    line2 = F_HANDLE.readline()

    ann1 = gff.BaseGFFDict(line1)
    ann2 = gff.BaseGFFDict(line2)

    assert hash(ann1) != hash(ann2)


@with_setup(setup=setup_gff)
def test_basegffdict_to_string():

    line = F_HANDLE.readline()

    ann1 = gff.BaseGFFDict(line)
    ann2 = gff.BaseGFFDict(ann1.to_string())

    eq_(hash(ann1), hash(ann2))


@with_setup(setup=setup_hmmer_parse)
def test_gffkegg_from_hmmer():
    checks = (
        'contig-1442648',
        'K00001_4479_poaceae',
        693,
        894,
        'K00001',
        '4479',
        'poaceae'
    )
    ann = gff.GFFKegg.from_hmmer(HMMER_HANDLE.readline(), AA_SEQS, NUC_SEQS)

    eq_(
        (ann.seq_id, ann.attributes.name, ann.attributes.aa_from,
         ann.attributes.aa_to, ann.attributes.ko, ann.attributes.taxon_id,
         ann.attributes.taxon
         ),
        checks
    )


@with_setup(setup=setup_hmmer_parse)
def test_gffkegg_to_gff():
    ann = gff.GFFKegg.from_hmmer(HMMER_HANDLE.readline(), AA_SEQS, NUC_SEQS)
    ann.attributes.ko_idx = 'K00001.1'
    ann = ann.to_gtf()

    eq_(
        (ann.attributes.gene_id, ann.attributes.transcript_id),
        ('K00001.1', 'K00001.1')
    )


def test_gffkegg_get_taxon_id1():
    ann = gff.GFFKegg.from_hmmer(HMMER_HANDLE.readline(), AA_SEQS, NUC_SEQS)
    ann.attributes.taxon_id = 12
    ann.attributes.blast_taxon_idx = 1
    eq_(ann.get_taxon_id(), 1)


def test_gffkegg_get_taxon_id2():
    ann = gff.GFFKegg.from_hmmer(HMMER_HANDLE.readline(), AA_SEQS, NUC_SEQS)
    ann.attributes.taxon_id = 12
    ann.attributes.blast_taxon_idx = 1
    eq_(ann.get_taxon_id(prefer_blast=False), 12)