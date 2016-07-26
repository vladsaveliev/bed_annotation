#!/usr/bin/env python
import os
from collections import defaultdict, OrderedDict
import sys
from optparse import OptionParser
from os.path import join, dirname, splitext, isfile, isdir

import GeneAnnotation as ga
from Utils.bed_utils import bgzip_and_tabix, SortableByChrom, sort_bed
from Utils.file_utils import adjust_path, verify_file, open_gzipsafe, add_suffix, verify_dir
from Utils.logger import err, info, critical, debug, warn
import Utils.reference_data as ref
from Utils import gtf
from Utils import logger


def main():
    description = '''
Usage:
    ' + __file__ + ' hg19 [db.gtf]
'''

    options = [
        (['--debug'], dict(dest='debug', action='store_true', default=False)),
    ]
    parser = OptionParser(description=description)
    for args, kwargs in options:
        parser.add_option(*args, **kwargs)
    opts, args = parser.parse_args()
    if len(args) == 0:
        parser.exit(1, 'Please provide genome name as the first argument')
    logger.is_debug = opts.debug

    genome_name = args[0]
    canonical_transcripts_ids = ref.get_canonical_transcripts_ids(genome_name)
    if len(args) > 1:
        gtf_fpath = args[1]
    else:
        gtf_fpath = ga.ensembl_gtf_fpath(genome_name)
    if not isfile(gtf_fpath):
        if not gtf_fpath.endswith('.gz'):
            gtf_fpath += '.gz'
    gtf_fpath = verify_file(gtf_fpath)

    debug('Reading the GTF database')
    db = gtf.get_gtf_db(gtf_fpath)

    debug('Reading biomart data')
    features_by_ens_id = dict()

    if isfile(ga.biomart_fpath(genome_name)):
        with open(ga.biomart_fpath(genome_name)) as f:
            for i, l in enumerate(f):
                if i == 0: continue
                bm_tx_id, refseq_id, gc, bm_tx_biotype, _, bm_tsl, hugo_gene, bm_gname = l.strip('\n').split('\t')
                features_by_ens_id[bm_tx_id] = (bm_tx_id, refseq_id, gc, bm_tx_biotype, bm_tsl, hugo_gene, bm_gname)

    output_fpath = join('Ensembl', genome_name, 'ensembl.bed')
    unsorted_output_fpath = add_suffix(output_fpath, 'unsorted')
    debug('Processing features, writing to ' + unsorted_output_fpath)

    def _get(_rec, _key):
        val = _rec.attributes.get(_key)
        if val is None:
            return None
        assert len(val) == 1, (_key, str(val))
        return val[0]

    num_tx_not_in_biomart = 0
    num_tx_diff_gene_in_biomart = 0

    with open(unsorted_output_fpath, 'w') as out:
        out.write('\t'.join(ga.BedCols.names[i] for i in ga.BedCols.cols[:-4]) + '\n')

        for rec in db.all_features(order_by=('seqid', 'start', 'end')):
            if rec.featuretype == 'gene':
                continue
            tx_id = _get(rec, 'transcript_id')
            gname = _get(rec, 'gene_name')
            tx_biotype = _get(rec, 'transcript_biotype')
            tsl = _get(rec, 'transcript_support_level')

            bm_tx_id, refseq_id, gc, bm_tx_biotype, bm_tsl, hugo_gene, bm_gname = features_by_ens_id.get(tx_id, ['.']*7)

            if bm_gname in ['', '.', None]:
                if rec.featuretype == 'transcript':
                    num_tx_not_in_biomart += 1
                continue
            if bm_gname != gname:
                if rec.featuretype == 'transcript':
                    num_tx_diff_gene_in_biomart += 1
                continue
            tx_biotype = bm_tx_biotype
            if rec.end - rec.start < 0:
                continue
            tsl = bm_tsl.split()[0].replace('tsl', '') if bm_tsl else None

            fs = [None] * len(ga.BedCols.cols[:-4])
            if not rec.chrom.startswith('chr'):
                rec.chrom = 'chr' + rec.chrom.replace('MT', 'M')
            fs[:6] = [rec.chrom,
                      str(rec.start - 1),
                      str(rec.end),
                      gname,
                      rec.attributes.get('exon_number', ['.'])[0],
                      rec.strand]
            fs[ga.BedCols.FEATURE] = rec.featuretype or '.'
            fs[ga.BedCols.BIOTYPE] = tx_biotype or '.'
            fs[ga.BedCols.ENSEMBL_ID] = tx_id or '.'
            # fs[ga.BedCols.REFSEQ_ID] = refseq_id or '.'
            # fs[ga.BedCols.IS_CANONICAL] = 'canonical' if refseq_id in canonical_transcripts_ids else ''
            fs[ga.BedCols.TSL] = tsl or '.'
            fs[ga.BedCols.HUGO] = hugo_gene or '.'
            # fs[ga.BedCols.names[ga.BedCols.GC]] = gc
            if len(fs) == 12:
                print fs
            out.write('\t'.join(fs) + '\n')

    if num_tx_not_in_biomart:
        warn(str(num_tx_not_in_biomart) + ' transcripts not found in biomart')
    if num_tx_diff_gene_in_biomart:
        warn(str(num_tx_diff_gene_in_biomart) + ' transcripts have a different gene name in biomart')

    debug('Sorting results')
    sort_bed(unsorted_output_fpath, output_fpath, fai_fpath=ref.get_fai(genome_name), genome=genome_name)
    os.remove(unsorted_output_fpath)
    bgzip_and_tabix(output_fpath)

    # with open(output_fpath, 'w') as out:
    #     for feature in db.features_of_type('transcript', order_by=("seqid", "start", "end")):
    #         chrom = feature.chrom
    #         start = feature.start
    #         end = feature.end
    #         attributes = feature.attributes.keys()
    #         strand = feature.strand
    #         name = (feature['gene_name'][0] if 'gene_name' in attributes else
    #                 feature['gene_id'][0])
    #         line = "\t".join([str(x) for x in [chrom, start, end, name, ".",
    #                                            strand]])
    #         out.write(line + "\n")


    # db_bed = gtf.gtf_to_bed(gtf_db_fpath, out_dir)


if __name__ == '__main__':
    main()
