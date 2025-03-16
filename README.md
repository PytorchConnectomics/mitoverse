# mitoverse3D

## 3D EM Datasets with Mitochondria Annotation
For some datasets, we converted the binary segmentation into instance segmentation.

|Microscope| Dataset  |    Specie   | Age   | Tissue | Avg Shape (xyz)   | Resolution   | # Mitos   |
|----------|----------|-------------|-------|--------|-------------------|--------------|-----------|
|FIB-SEM   |[CellMap'25](https://cellmapchallenge.janelia.org/)|mixed|||     (219,210,217)x147  | 8x8x8        | 1580      |
|FIB-SEM   |[Xie'23](https://github.com/bowang-lab/MAESTER)|Mouse||Pancreas Islet β cell|(874,669,979)x7    | 16x16x16     |         |
|FIB-SEM   |[Conrad'23 (MitoNet)](https://volume-em.github.io/empanada.html)|mixed|||(546,446,242)x5    | ~15x15x15     | 550        |
|FIB-SEM   |[Mekuč'20 (UroCell)](https://github.com/MancaZerovnikMekuc/UroCell)|Mouse|6-8w|urinary bladder|(256,256,256)x5|16x16x15| 287  |
|FIB-SEM   |[Lucchi'13](https://www.epfl.ch/labs/cvlab/data/data-em/)|Mouse|?|Hippocampus|(512,768,82)|10x10x10|70|
|ssSEM     |[Wei'20 (MitoEM)](https://mitoem.grand-challenge.org/)|Rat|Adult|Primary visual cortex (layer II/III)|(512,512,500)x64|8x8x30| 8201|
|          |          |  Human      | Adult |Temporal lobe (layer II) | (512,512,500)x64    | 8x8x30       | 13537     |
|ssSEM     |[Casser'20 (Kasthuri++)](https://sites.google.com/view/connectomics/) | Mouse     |       |Somatosensory (layer IV/V) | (699,791,80)x2      |12x12x30      | 267       |
|ssSEM     |[Xiao'18](https://www.frontiersin.org/journals/neuroanatomy/articles/10.3389/fnana.2018.00092/full)|Mouse||cortex|(2156,2104,31)|8x8x50|   468  |
|SBF-SEM   |[Guay'21](https://leapmanlab.github.io/dense-cell/)|Human||Platelet|(667,736,65)x3|10x10x50|    |
|SBF-SEM   |[Haberl'18](https://github.com/CRBS/cdeep3m/)|Mouse|||(256,256,15)x2|10x10x24|    |


## Acknowledgement
- [Aswath et al. 2023. Segmentation in large-scale cellular electron microscopy with deep learning: A literature survey](https://arxiv.org/abs/2206.07171)
