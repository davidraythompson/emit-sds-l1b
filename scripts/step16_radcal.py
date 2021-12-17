# David R Thompson
import numpy as np
import pylab as plt

q,wl,fwhm = np.loadtxt('../data/EMIT_Wavelengths_20211117.txt').T * 1000.0

def resample(wl_old, spectrum, method='linear'):
  p = interp1d(wl_old, spectrum, method=method, fill_value='extrapolate', bounds_error=False)
  return p(wl)

# Load irradiance
# translate uncertainty from percenmt to one sigma irradiance
wl_irr, irradiance, irradiance_uncert = np.loadtxt('../data/ogse/tvac2/lamp_s1344_irradiance.txt').T
irradiance = resample(wl_irr, irradiance)
irradiance_uncert = irradiance_uncert / 100.0 * irradiance
irradiance_uncert = resample(wl_irr, irradiance_uncert)

# Mirror transmittance
wl_mirror, mirror_rfl = np.loadtxt('../data/ogse/tvac2/mirror_coating_reflectance.txt').T
mirror_rfl = resample(wl_mirror, mirror_wl)
mirror_uncert = np.ones(len(mirror_rfl)) * 0.01

# Spectralon reflectance
wl_spec, spectralon_rfl, spectralon_uncert =\
     np.loadtxt('../data/ogse/tvac2/panel_srt-99-120_reflectance.txt').T  
spectralon_rfl = resample(wl_spec, spectralon_rfl)
spectralon_uncert = resample(wl_spec, spectralon_uncert)

# Window transmittance
wl_window, window_trans = np.loadtxt('../data/ogse/tvac2/window_infrasil301-302_transmittance.txt').T
window_trans = resample(wl_window, window_trans)
window_uncert = np.ones(len(window_trans)) * 0.01

# BRDF
brdf_factor = np.ones(len(wl)) * 1.015
brdf_uncert = np.ones(len(wl)) * 1.01

# Radiance 
radiance = irradiance * spectralon_rfl * mirror_rfl * window_trans / np.pi * brdf_factor

distance_uncert = 0.0015875 # meters
distance = 0.5
distance_uncert_rdn =( 1-(0.5**2)/((0.5+distance_uncert)**2)) * radiance

# Derivatives of radiance
drdn_dirr    =              spectralon_rfl * mirror_rfl * window_trans / np.pi * brdf_factor
drdn_dspec   = irradiance *                  mirror_rfl * window_trans / np.pi * brdf_factor
drdn_dtrans  = irradiance * spectralon_rfl * mirror_rfl                / np.pi * brdf_factor
drdn_brdf    = irradiance * spectralon_rfl * mirror_rfl * window_trans / np.pi 
drdn_dmirror = irradiance * spectralon_rfl *              window_trans / np.pi * brdf_factor

rdn_uncert = np.sqrt((drdn_dirr * irradiance_uncert)**2 + \
                     (drdn_dspec * spectralon_uncert)**2 + \
                     (drdn_dtrans * window_uncert)**2 + \
                     (drdn_dbrdf * brdf_uncert)**2 + \
                     (drdn_dmirror * mirror_uncert)**2)

plt.plot(wl,rdn_uncert)
plt.show()
