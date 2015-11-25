#!/bin/bash

# Some tools require a contact email
export EMAIL=your@email

# Requirements
#
# software 	- version tested
# mgkit 	- 0.2.1
# wget 		- any
# velvet 	- 1.2.10
# bowtie2 	- 2.2.6 / 2.1.0
# khmer 	- 2.0
# hmmer 	- 3.1b2 / 3.1b1
# clustalo 	- 1.2.1
# megahit	- 1.0.3

# Requirements specific for Mac OS X (El Capitan, 10.11), uncomment these lines
# brew install wget homebrew/science/velvet homebrew/science/bowtie2 \
# homebrew/science/samtools pyenv-virtualenv homebrew/science/hmmer \
# homebrew/science/clustal-omega

# Memory ~6 GB for khmer normalisation
# ~3.5 GB for megahit
# ~0.5 GB for bowtie2

# Using data from the following project:
# http://www.ebi.ac.uk/ena/data/view/PRJEB6461
# Samples:
# I (Influent)
# B (Buffering)
# SA (Secondary aeration)
# PA (Primary aeration)
# SD (Sludge digestion)
mkdir seqs
cd seqs
#download data
wget ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/B_R1.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/B_R2.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/I_R1.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/I_R2.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/PA_R1.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/PA_R2.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/SA_R1.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/SA_R2.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/SD_R1.fastq.gz ftp://ftp.sra.ebi.ac.uk/vol1/ERA315/ERA315794/fastq/SD_R2.fastq.gz

# Normalisation of the reads
# Khmer when using paired reads works best when are interleaved
# Moreover, it requires the older Casava type of header
# The sequences are trimmed by 20 bp and fed to the khmer
# script interleave-reads.py (the quality is not good in the last 20 bp)
interleave-reads.py --gzip -o all-interleaved.fq.gz \
<(
python - <<END
import HTSeq, sys, glob
files = glob.glob('*R1.fastq.gz')
for fname in files:
    for record in HTSeq.FastqReader(fname):
        record = record[:-20] # cut 20 bp
        # HTSeq adds '[part]' to the header, the next line cut it
        record.name = record.name[:-6]
        record.write_to_fastq_file(sys.stdout)
END
) \
<(
python - <<END
import HTSeq, sys, glob
files = glob.glob('*R2.fastq.gz')
for fname in files:
    for record in HTSeq.FastqReader(fname):
        record = record[:-20]
        record.name = record.name[:-6]
        record.write_to_fastq_file(sys.stdout)
END
)
# Normalisation takes out almost 7% of the reads
normalize-by-median.py -k 24 -p -o normalised.fq.gz --gzip -M 6e9 all-interleaved.fq.gz
# rm all-interleaved.fq.gz

# megahit manages to assemble the data
# add -t N to use more processors
megahit --presets meta --verbose --min-contig-len 100 --12 normalised.fq.gz -o megahit-out
# megahit used spaces in the sequence headers so it may create problems later
# one solution is to assign to each contig a new random sequence and then
# keep track of those in a json dictionary for later (if needed)
python - <<END
from mgkit.io import fasta
from uuid import uuid4
import json

seq_dict = {}
with open('final-contigs.fa', 'w') as f:
    for name, seq in fasta.load_fasta('megahit-out/final.contigs.fa'):
        uid = str(uuid4())
        seq_dict[uid] = name
        fasta.write_fasta_sequence(f, uid, seq)

json.dump(seq_dict, open('seq-dict.json', 'w'))
END
rm -R megahit-out
cd ..

# Get the nitrogen metabolism KOs
export GENES=`python - <<END
from mgkit import kegg
k = kegg.KeggClientRest()
print " ".join(k.link_ids('ko', 'ko00910')['ko00910'])
END`

#download offline data (only taxonomy)
download_data -p -x -m $EMAIL

download_profiles -o profiles -ko $GENES -r order -l bacteria -m $EMAIL -t mg_data/taxonomy.pickle

unset GENES

#Profile alignments and build
for file in profiles/*.fa; do
	echo $file `basename $file .fa`
    clustalo -i $file -o profiles/`basename $file .fa`.afa ;
    hmmbuild profiles/`basename $file .afa`.hmm profiles/`basename $file .fa`.afa;
done
#Make one file for all profiles
cat profiles/*.hmm > profiles.hmm

#translation of the assembly in AA
translate_seq seqs/final-contigs.fa final-contigs.aa.fa

#HMMER command line
# add --cpu N to use more processors
hmmsearch -o /dev/null --domtbl hmmer_dom-table.txt profiles.hmm final-contigs.aa.fa
#convert into annotations
hmmer2gff -d -o assembly.gff final-contigs.aa.fa hmmer_dom-table.txt
# Filter annotations and add information from Kegg
# most scripts working on GFF files allow to pipe their input/output
# First remove annotations with a bit score less than 40, then filter
# overlapping annoations and finally add gene descriptions and pathways for
# for each annotations. `cat` is not necessary, since the input/output can
# specified with a `-` (dash), which is standard
cat assembly.gff | filter-gff values -b 40 | filter-gff overlap -s 100 | \
add-gff-info kegg -c $EMAIL -v -d -p > assembly.filt.gff

#bowtie2
bowtie2-build seqs/final-contigs.fa final-contigs
for file in seqs/*R1.fastq.gz; do
	BASENAME=`basename $file _R1.fastq.gz`
	# echo $file $BASENAME seqs/"$BASENAME"_R2.fastq.gz
	bowtie2 -N 1 -x final-contigs --local --sensitive-local \
	-1 $file -2 seqs/"$BASENAME"_R2.fastq.gz \
	--rg-id $BASENAME --rg PL:Illumina --rg PU:Illumina-MiSeq \
	--rg SM:$BASENAME | samtools view -Sb - > $BASENAME.bam;
done

#samtools
for file in *.bam; do
	# samtools 1.2 (at least) needs to specify the format and temp file prefix
	samtools sort -T tmp.$file -O bam -o `basename $file .bam`-sort.bam $file;
	mv `basename $file .bam`-sort.bam $file;
	samtools index $file;
done

#index for the assembly (required by GATK and samtools)
#.fai index
samtools faidx seqs/final-contigs.fa

#add coverage data
export SAMPLES=$(for file in *.bam; do echo -a `basename $file .bam`,$file ;done)
add_coverage_to_gff -v $SAMPLES assembly.filt.gff assembly.filt.cov.gff

#SNP calling using samtools
for file in *.bam; do
	samtools mpileup -Iuvf assembly.fa $file > `basename $file`.vcf;
done

samtools mpileup -t DP,DV -s -q 10 -Iuvf assembly.fa *.bam

#fasta .dict file, needed for GATK
wget https://github.com/broadinstitute/picard/releases/download/1.140/picard-tools-1.140.zip
unzip picard-tools-1.140.zip
java -jar picard-tools-1.140/picard.jar CreateSequenceDictionary \
	R=assembly.fa O=assembly.dict

#merge vcf
export SAMPLES=$(for file in *-sort.bam.vcf; do echo -V:`basename $file -sort.bam.vcf` $file ;done)
java -Xmx1g -jar GATK/GenomeAnalysisTK.jar \
	  -R assembly.fa -T CombineVariants -o assembly.vcf \
	  -genotypeMergeOptions UNIQUIFY \
	  $SAMPLES
unset SAMPLES

#snp_parser
export SAMPLES=$(for file in *.bam; do echo -m `basename $file .bam`;done)
snp_parser -v -g assembly.uniprot.gff \
	-p assembly.vcf \
	-a assembly.fasta \
 	$SAMPLES
unset SAMPLES
