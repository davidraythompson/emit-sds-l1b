# David R Thompson
import argparse, sys, os
import numpy as np
import pylab as plt
from glob import glob
from spectral.io import envi
from scipy.stats import norm
from scipy.linalg import solve, inv
from astropy import modeling
from sklearn.linear_model import RANSACRegressor
from scipy.optimize import minimize
from scipy.interpolate import BSpline,interp1d
from skimage.filters import threshold_otsu
from scipy.ndimage import gaussian_filter
from makelinearity import linearize
from emit_fpa import linearity_nbasis
import scipy.linalg as linalg
import json


def find_header(infile):
  if os.path.exists(infile+'.hdr'):
    return infile+'.hdr'
  elif os.path.exists('.'.join(infile.split('.')[:-1])+'.hdr'):
    return '.'.join(infile.split('.')[:-1])+'.hdr'
  else:
    raise FileNotFoundError('Did not find header file')


def main():

    description = "Calculate Linearity Correction"

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('input',nargs='+')
    parser.add_argument('basis')
    parser.add_argument('--draft',default=None)
    parser.add_argument('output')
    args = parser.parse_args()

    xs,ys = [],[]
    nfiles = len(args.input) 
    illums =[] 
    out = np.zeros((480,1280,linearity_nbasis))
    if args.draft is not None:
        out = envi.open(args.draft+'.hdr').load()

    basis = np.squeeze(envi.open(args.basis+'.hdr').load())
    evec = np.squeeze(basis[1:,:].T)
    if evec.shape[1] != linearity_nbasis:
        raise IndexError('Linearity basis does not match file size')
    evec[np.isnan(evec)] = 0
    for i in range(linearity_nbasis):
      evec[:,i] = evec[:,i] / linalg.norm(evec[:,i])
    print(linalg.norm(evec,axis=1),linalg.norm(evec,axis=0))
    mu = np.squeeze(basis[0,:])
    mu[np.isnan(mu)] = 0
    data, last_fieldpoint = [], -9999


    for fi,infilepath in enumerate(args.input):

        print('loading %i/%i: %s'%(fi,len(args.input),infilepath))
        toks = infilepath.split('_')
        for tok in toks:
            if 'Field' in tok:
               simple = tok.replace('Field','')
               fieldpoint= int(simple)
               if last_fieldpoint<0: 
                   last_fieldpoint = fieldpoint
               elif last_fieldpoint != fieldpoint:
                   raise IndexError('One fieldpoint per call. Use --draft')
               active_cols = np.arange(fieldpoint-37-1,fieldpoint+38-1,dtype=int)
            elif 'candelam2' in tok:
               simple = tok.split('.')[0]
               simple = simple.replace('PD','')
               simple = simple.replace('candelam2','')
               simple = simple.replace('p','.')
               illums.append(float(simple))
        
        infile = envi.open(find_header(infilepath))
        
        if int(infile.metadata['data type']) == 2:
            dtype = np.uint16
        elif int(infile.metadata['data type']) == 4:
            dtype = np.float32
        else:
            raise ValueError('Unsupported data type')
        if infile.metadata['interleave'] != 'bil':
            raise ValueError('Unsupported interleave')
        
        rows = int(infile.metadata['bands'])
        columns = int(infile.metadata['samples'])
        lines = int(infile.metadata['lines'])
        nframe = rows * columns
        
        sequence = []

        infile = envi.open(infilepath+'.hdr')
        frame_data = infile.load().mean(axis=0)
        data.append(frame_data[active_cols,:])
    data = np.array(data) 
    print(data.shape)
       #with open(infilepath,'rb') as fin:
       #
       #    print(infilepath)
       #    for line in range(lines):
       #
       #        # Read a frame of data
       #        frame = np.fromfile(fin, count=nframe, dtype=dtype)
       #        frame = np.array(frame.reshape((rows, columns)),dtype=np.float32)
       #        sequence.append(frame)
       #        
       #sequence = np.array(sequence)
       #data[fi,:,active_cols] = np.mean(sequence[:,:,active_cols], axis=0).T
               
    #for wl in np.arange(25,313):
    for wl in np.arange(100,313):
   
       for mycol,col in enumerate(active_cols):

         DN = data[:,mycol,wl]
         L = np.array(illums) 
         resamp = linearize(DN, L,plot=(wl>50 and col>40 and col<1200))
         coef = (resamp - mu)[np.newaxis,:] @ evec
         out[wl,col,:] = coef[:linearity_nbasis]
         if wl>50 and col>40 and col<1200:
             plt.plot(resamp)
             plt.plot(resamp-mu)
             plt.plot(np.squeeze(np.sum(evec*coef,axis=1)) + mu,'k.')
             plt.show()
         print('!',wl,col,coef)

    envi.save_image(args.output+'.hdr',np.array(out,dtype=np.float32),ext='',force=True)

if __name__ == '__main__':

    main()
