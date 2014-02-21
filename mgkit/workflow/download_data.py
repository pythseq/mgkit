"""
The scripts downloads the data that is used by the framework for some of its
functions. It's mostly a shortcut to call the download_data function that is
present in every module that is in the package mappings and in the kegg module.

The Kegg data is the only "required" data at the moment, because it's used to
download the sequence data (via the donwload_profiles script) for the
profiling. It is the only data that can't be saved unless it's fully
downloaded.

Kegg data is required by the mappers currently supported, and its download
takes longer. The mappers handle timeouts and if exceptions are raised the data
is saved and the download is resumed when the script is started again.

The only option required, is the email contact for the person using the script;
this is used to make sure that the API requirements in Uniprot are fullfilled
and they can contact the person using the script is any problem arise.
"""
import os
import argparse
import logging
import mgkit
import mgkit.logger
import mgkit.kegg
import mgkit.mappings.cazy
import mgkit.mappings.eggnog
import mgkit.taxon
import mgkit.net

try:
    import mgkit.mappings.go
    SKIP_GO = False
except ImportError:
    SKIP_GO = True

LOG = logging.getLogger(__name__)

TAXONONY_URL = "http://www.uniprot.org/taxonomy/?query=*&format=tab&compress=no"


def set_parser():
    """
    Sets command line arguments parser
    """
    parser = argparse.ArgumentParser(
        description='SNPs analysis, requires a vcf file and SNPDat results',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '-o',
        '--output-dir',
        default='mg_data',
        action='store',
        help='Ouput directory'
    )
    parser.add_argument(
        '-k',
        '--kegg',
        default='kegg.pickle',
        action='store',
        help='Kegg data file name'
    )
    parser.add_argument(
        '-c',
        '--cazy',
        default='cazy.pickle',
        action='store',
        help='CaZy data file name'
    )
    parser.add_argument(
        '-g',
        '--go',
        default='go.pickle',
        action='store',
        help='Gene Onthology data file name'
    )
    parser.add_argument(
        '-e',
        '--eggnog',
        default='eggnog.pickle',
        action='store',
        help='eggNOG data file name'
    )
    parser.add_argument(
        '-t',
        '--taxonomy',
        default='taxonomy.pickle',
        action='store',
        help='Taxonomy data file name'
    )
    parser.add_argument(
        '-p',
        '--no-mappings',
        default=True,
        action='store_false',
        help='Use to download only Kegg and Taxonomy data'
    )
    parser.add_argument(
        '-m',
        '--email',
        required=True,
        action='store',
        help='email address to use for Uniprot communications'
    )
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_const',
        const=logging.DEBUG,
        default=logging.INFO,
        help='more verbose'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s {0}'.format(mgkit.__VERSION__)
    )
    return parser


def main():
    "Main function"
    options = set_parser().parse_args()

    #configs log and set log level
    mgkit.logger.config_log(options.verbose)

    try:
        os.mkdir(options.output_dir)
    except OSError:
        LOG.info('Directory exists')

    LOG.info("Downloading Uniprot Taxonomy data")
    taxonomy_path = os.path.join(options.output_dir, options.taxonomy)
    if not os.path.exists(taxonomy_path):
        taxonomy = mgkit.taxon.UniprotTaxonomy()
        taxonomy.read_taxonomy(mgkit.net.url_open(TAXONONY_URL))
        taxonomy.save_data(taxonomy_path)

    kegg_path = os.path.join(options.output_dir, options.kegg)
    if not os.path.exists(kegg_path):
        mgkit.kegg.download_data(fname=kegg_path, contact=options.email)

    if options.no_mappings:
        LOG.info("Downloading additional mappings")
        mgkit.mappings.cazy.download_data(
            options.email,
            kegg_data=kegg_path,
            cazy_data=os.path.join(options.output_dir, options.cazy)
        )
        mgkit.mappings.eggnog.download_data(
            options.email,
            kegg_data=kegg_path,
            eggnog_data=os.path.join(options.output_dir, options.eggnog)
        )
        if SKIP_GO:
            LOG.warning(
                "Cannot import mgkit.mappings.go, will be skipped"
            )
            return 1
        mgkit.mappings.go.download_data(
            options.email,
            kegg_data=kegg_path,
            go_data=os.path.join(options.output_dir, options.go)
        )

    LOG.info("Download completed")

    return 0

if __name__ == '__main__':
    main()