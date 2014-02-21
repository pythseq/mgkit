"""
Translate nucleotidic sequence in amino acidic sequences
"""

import argparse
import logging
import mgkit
import itertools
from .. import logger
from ..io.fasta import load_fasta, write_fasta_sequence
from joblib import Parallel, delayed
from ..utils import trans_tables
from ..utils.sequence import translate_sequence

LOG = logging.getLogger(__name__)


def set_parser():
    "argument parser configuration"
    parser = argparse.ArgumentParser(
        description='Translate sequences from nucleotidic to amino acidic',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        'input_file',
        action='store',
        help='input file with aa sequences',
        type=argparse.FileType('r')
    )
    parser.add_argument(
        'output_file',
        action='store',
        help='output file with aa sequences',
        type=argparse.FileType('w')
    )
    parser.add_argument(
        '-t',
        '--trans-table',
        default='universal',
        action='store',
        choices=[
            table_name.lower() for table_name in dir(trans_tables)
            if not table_name.startswith('_')
        ],
        help='translation table'
    )
    parser.add_argument(
        '-p',
        '--processors',
        action='store',
        default=1,
        type=int,
        help='Number of processors to use'
    )
    parser.add_argument(
        '-n',
        '--buffer-size',
        action='store',
        default=50000,
        type=int,
        help='Number of sequences to read/write at a time'
    )
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_const',
        const=logging.DEBUG,
        default=logging.INFO,
        help='more verbose'
    )
    parser.add_argument('--version', action='version',
                        version='%(prog)s {0}'.format(mgkit.__VERSION__))

    return parser


def load_trans_table(table_name):
    return getattr(trans_tables, table_name.upper())


def translate_seq(name, seq, trans_table):
    seqs = []
    header = "{0}-{1}{2}"
    for start in range(3):
        seqs.append(
            (header.format(name, 'f', start),
             translate_sequence(seq, start, trans_table, False))
        )
        seqs.append(
            (header.format(name, 'r', start),
             translate_sequence(seq, start, trans_table, True))
        )
    return seqs


def translate_buff(jobs, buff_seqs, trans_table):

    aa_seqs = jobs(
        delayed(translate_seq)(name, seq, trans_table)
        for name, seq in buff_seqs
    )

    # LOG.info("Finished translating buffer")

    return aa_seqs


def main():
    options = set_parser().parse_args()

    #configs log and set log level
    logger.config_log(options.verbose)

    trans_table = load_trans_table(options.trans_table)

    nuc_seqs = list(load_fasta(options.input_file))

    LOG.info("Using %d processor(s)", options.processors)
    jobs = Parallel(n_jobs=options.processors, verbose=0)

    for index in xrange(0, len(nuc_seqs), options.buffer_size):
        LOG.info(
            "Translating file position %d-%d",
            index,
            index+options.buffer_size
        )
        aa_seqs = translate_buff(
            jobs,
            nuc_seqs[index:index+options.buffer_size],
            trans_table
        )
        for name, seq in itertools.chain(*aa_seqs):
            write_fasta_sequence(options.output_file, name, seq)

    options.output_file.close()

    return 0

if __name__ == '__main__':
    main()