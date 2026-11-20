"""Fixed CPU spherical K-means for QKV node-prototype context only."""
from __future__ import annotations
import argparse
import numpy as np
from common import load_config, load_embeddings, run_dir, write_json

def normalize(x):
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--config',required=True); p.add_argument('--clusters',type=int,default=32); p.add_argument('--seed',type=int,default=17); p.add_argument('--iterations',type=int,default=100); a=p.parse_args()
    out=run_dir(load_config(a.config))/'node_clustering'; out.mkdir(parents=True,exist_ok=True)
    vectors,_=load_embeddings(load_config(a.config)); x=normalize(np.asarray(vectors,dtype=np.float32)); rng=np.random.default_rng(a.seed); c=x[rng.choice(len(x),a.clusters,replace=False)].copy(); labels=np.full(len(x),-1,dtype=np.int32)
    for step in range(a.iterations):
        nxt=np.argmax(x@c.T,axis=1).astype(np.int32)
        if np.array_equal(labels,nxt): break
        labels=nxt
        for k in range(a.clusters):
            if np.any(labels==k): c[k]=x[labels==k].mean(axis=0)
        c=normalize(c)
    np.save(out/'labels.npy',labels); np.save(out/'centroids.npy',c)
    write_json(out/'manifest.json',{'kind':'fixed spherical K-means Node context for QKV probe','nodes':len(x),'dimension':int(x.shape[1]),'clusters':a.clusters,'seed':a.seed,'iterations':step,'query_or_gold_used':False,'counts':np.bincount(labels,minlength=a.clusters).tolist()})
    print(out)
if __name__=='__main__': main()
