package seg

// Copied into erigon 5f62f4ed's db/seg by build-compactlatest.sh; not part of upstream erigon.

// WordsFileOffset is the file offset of Getter offset 0, so a word's Getter offsets plus this are
// where its bytes sit in the file, which is what decides the pages a read touches.
func (d *Decompressor) WordsFileOffset() uint64 { return d.wordsFileOffset }
