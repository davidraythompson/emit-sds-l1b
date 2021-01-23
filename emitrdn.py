#! /usr/bin/env python
#
#  Copyright 2020 California Institute of Technology
#
# EMIT Radiometric Calibration code
# Author: David R Thompson, david.r.thompson@jpl.nasa.gov

import scipy.linalg
import os, sys
import scipy as sp
import numpy as np
from spectral.io import envi
from datetime import datetime, timezone
from scipy import linalg, polyfit, polyval
import json
import logging
import argparse
import multiprocessing


header_template = """ENVI
description = {{Calibrated Radiance, microWatts per (steradian nanometer [centemeter squared])}}
samples = {columns_raw}
lines = {lines}
bands = {channels_raw}
header offset = 0
file type = ENVI Standard
data type = 4
interleave = bil
byte order = 0
wavelength units = Nanometers
wavelength = {{{wavelength_string}}}
fwhm = {{{fwhm_string}}}
band names = {{{band_names_string}}}"""

      
class Config:

    def __init__(self, filename, input_file='', output_file=''):

        # Load calibration file data
        with open(filename,'r') as fin:
         self.__dict__ = json.load(fin)
        try:
           self.dark, _ = sp.fromfile(self.dark_frame_file,
                dtype = sp.float32).reshape((2, self.channels_raw, 
                    self.columns_raw))
           _, self.wl, self.fwhm = \
                sp.loadtxt(self.spectral_calibration_file).T * 1000
           self.srf_correction = sp.fromfile(self.srf_correction_file,
                dtype = sp.float32).reshape((self.channels_raw, 
                    self.channels_raw))
           self.crf_correction = sp.fromfile(self.crf_correction_file,
                dtype = sp.float32).reshape((self.columns_raw, 
                    self.columns_raw))
           self.bad = sp.fromfile(self.bad_element_file,
                dtype = sp.uint16).reshape((self.channels_raw, 
                    self.columns_raw))
           self.flat_field = sp.fromfile(self.flat_field_file,
                dtype = sp.float32).reshape((2, self.channels_raw, 
                    self.columns_raw))[0,:,:]
           self.radiometric_calibration, _, _ = \
                sp.loadtxt(self.radiometric_coefficient_file).T
           self.linearity = sp.fromfile(self.linearity_file, 
                dtype=sp.uint16).reshape((65536,))
        except ValueError:
            logging.error('Incorrect file size for calibration data')
        except AttributeError:
            logging.error('One or more missing calibration files')

        # Check for NaNs in calibration data
        for name in ['dark', 'wl', 'srf_correction', 
                'crf_correction', 'bad', 'flat_field',
                'radiometric_calibration','linearity']:
            obj = getattr(self, name)
            invalid  = np.logical_not(sp.isfinite(obj))
            if invalid.sum() > 0:
                msg='Replacing %i non-finite values in %s' 
                logging.warning(msg % (invalid.sum(),name))
            obj[invalid]=0

        # Truncate flat field values, if needed
        if self.flat_field_limits is not None:
           lo, hi = self.flat_field_limits
           self.flat_field[self.flat_field < lo] = lo
           self.flat_field[self.flat_field > hi] = hi 

        # Size of regular frame and raw frame (with header)
        self.frame_shape = (self.channels, self.columns)
        self.nframe = sp.prod(self.frame_shape)
        self.raw_shape = (self.channels_raw + self.header_channels, self.columns_raw)
        self.nraw = sp.prod(self.raw_shape)

        # Form output metadata strings
        self.band_names_string = ','.join(['channel_'+str(i) \
                for i in range(len(self.wl))])
        self.fwhm_string =  ','.join([str(w) for w in self.fwhm])
        self.wavelength_string = ','.join([str(w) for w in self.wl])

        # Clean channels have no bad elements
        self.clean = sp.where(np.logical_not(self.bad).all(axis=1))[0]
        logging.warning(str(len(self.clean))+' clean channels')

        # Find the input files
        if len(input_file)>0:
            self.input_file = input_file
        if len(output_file)>0:
            self.output_file = output_file

        # Identify input file header
        if self.input_file.endswith('.img'):
            self.input_header = self.input_file.replace('.img','.hdr') 
        else:
            self.input_header = self.input_file + '.hdr'

        # Identify output file header
        if self.output_file.endswith('.img'):
            self.output_header = self.output_file.replace('.img','.hdr') 
        else:
            self.output_header = self.output_file + '.hdr'


def correct_pedestal_shift(frame, config):
    mean_dark = frame[config.dark_channels,:].mean(axis=0)
    return frame - mean_dark


def infer_bad(frame, col, config):
    '''Infer the value of a bad pixel'''
    bad = sp.where(config.bad[:,col])[0]
    sa = frame[config.clean,:].T @ frame[config.clean, col]
    norms = linalg.norm(frame[config.clean,:], axis=0).T
    sa = sa / (norms * norms[col])
    sa[col] = -9e99
    best = sp.argmax(sa)
    p = polyfit(frame[config.clean, best], frame[config.clean, col],1)
    new = frame[:,col]
    new[bad] = polyval(p, frame[bad, best])
    return new 

    
def fix_bad(frame, config):
    fixed = frame.copy()
    for col in sp.nonzero(config.bad.any(axis=0))[0]:
        fixed[:,col] = infer_bad(frame, col, config)
    return fixed


def subtract_dark(frame, config):
    return frame - config.dark


def correct_spatial_resp(frame, crf_correction):
    scratch = sp.zeros(frame.shape)
    for i in range(frame.shape[0]):
        scratch[i,:] = crf_correction @ frame[i,:] 
    return scratch


def correct_spectral_resp(frame, srf_correction):
    scratch = sp.zeros(frame.shape)
    for i in range(frame.shape[1]):
        scratch[:,i] = srf_correction @ frame[:,i]  
    return scratch


def correct_panel_ghost(frame, config):

    pg_template = sp.array([config.pg_template])
    ntemplate = len(config.pg_template)

    panel1 = sp.arange(config.panel_width)
    panel2 = sp.arange(config.panel_width,(2*config.panel_width))
    panel3 = sp.arange((2*config.panel_width),(3*config.panel_width))
    panel4 = sp.arange((3*config.panel_width),(4*config.panel_width))
 
    avg1 = frame[:,panel1].mean(axis=1)[:,sp.newaxis]
    avg2 = frame[:,panel2].mean(axis=1)[:,sp.newaxis]
    avg3 = frame[:,panel3].mean(axis=1)[:,sp.newaxis]
    avg4 = frame[:,panel4].mean(axis=1)[:,sp.newaxis]
  
    c1 = frame[:,panel1];
    c2 = frame[:,panel2];
    c3 = frame[:,panel3];
    c4 = frame[:,panel4];       
 
    coef1 = config.panel_ghost_correction * (c2+c3+c4);
    coef2 = config.panel_ghost_correction * (c1+c3+c4);
    coef3 = config.panel_ghost_correction * (c1+c2+c4);
    coef4 = config.panel_ghost_correction * (c1+c2+c3);       

    coef1[:,:ntemplate] = 1.6 * (avg2+avg3+avg4) @ pg_template
    coef2[:,:ntemplate] = 1.6 * (avg1+avg3+avg4) @ pg_template
    coef3[:,:ntemplate] = (avg1+avg2+avg4)@ pg_template
    coef4[:,:ntemplate] = (avg1+avg2+avg3)@ pg_template
            
    new = sp.zeros(frame.shape)
    new[:,panel1] = frame[:,panel1] + coef1;
    new[:,panel2] = frame[:,panel2] + coef2;
    new[:,panel3] = frame[:,panel3] + coef3;
    new[:,panel4] = frame[:,panel4] + coef4;

    return new


def main():

    description = "Radiometric Calibration"

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('config_file')
    parser.add_argument('input_file', nargs='?', default='')
    parser.add_argument('output_file', nargs='?', default='')
    parser.add_argument('--level', default='DEBUG',
            help='verbosity level: INFO, ERROR, or DEBUG')
    parser.add_argument('--log_file', type=str, default=None)
    args = parser.parse_args()

    config = Config(args.config_file, args.input_file, args.output_file)

    # Set up logging
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    if args.log_file is None:
        logging.basicConfig(format='%(message)s', level=args.level)
    else:
        logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=args.level, filename=args.log_file)

    logging.info('Starting calibration')
    lines = 0
    raw = 'Start'

    with open(config.input_file,'rb') as fin:
        with open(config.output_file,'wb') as fout:

            raw = sp.fromfile(fin, count=config.nraw, dtype=sp.int16)
            while len(raw)>0:

                # Read a frame of data
                if lines%10==0:
                    logging.info('Calibrating line '+str(lines))
                
                raw = np.array(raw, dtype=sp.float32)
                raw = raw.reshape(config.raw_shape)
                header = raw[:config.header_channels, :]
                frame  = raw[config.header_channels:, :]
                
                # Detector corrections
                frame = subtract_dark(frame, config)
                frame = correct_pedestal_shift(frame, config)
                frame = correct_panel_ghost(frame, config) 
                frame = frame * config.flat_field
                frame = fix_bad(frame, config)

                # Optical corrections
                frame = correct_spectral_resp(frame, config.srf_correction)
                frame = correct_spatial_resp(frame, config.crf_correction)

                # Absolute radiometry
                frame = (frame.T * config.radiometric_calibration).T
   
                # Reverse channels, catch NaNs, and write
                frame[sp.logical_not(sp.isfinite(frame))]=0
                if config.reverse_channels:
                    frame = sp.flip(frame, axis=0)
                sp.asarray(frame, dtype=sp.float32).tofile(fout)
                lines = lines + 1
            
                # Read next chunk
                raw = sp.fromfile(fin, count=config.nraw, dtype=sp.int16)

    params = {'lines': lines}
    params.update(globals())
    params.update(config.__dict__)
    with open(config.output_header,'w') as fout:
        fout.write(header_template.format(**params))

    logging.info('Done')


if __name__ == '__main__':

    main()
