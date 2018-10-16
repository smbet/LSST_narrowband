from builtins import zip
from builtins import object
import os
import numpy
from astropy.io import fits

from lsst.sims.utils.CodeUtilities import sims_clean_up
from lsst.sims.utils import _galacticFromEquatorial
from functools import reduce

__all__ = ["EBVmap", "EBVbase"]


def interp1D(z1, z2, offset):
    """ 1D interpolation on a grid"""

    zPrime = (z2-z1)*offset + z1

    return zPrime


class EBVmap(object):
    '''Class  for describing a map of EBV

    Images are read in from a fits file and assume a ZEA projection
    '''

    def __del__(self):
        self.hdulist.close()

    def readMapFits(self, fileName):
        """ read a fits file containing the ebv data"""

        self._file_name = fileName

        self.hdulist = fits.open(fileName)
        self.header = self.hdulist[0].header
        self.data = self.hdulist[0].data
        self.nr = self.data.shape[0]
        self.nc = self.data.shape[1]

        # read WCS information
        self.cd11 = self.header['CD1_1']
        self.cd22 = self.header['CD2_2']
        self.cd12 = 0.
        self.cd21 = 0.

        self.crpix1 = self.header['CRPIX1']
        self.crval1 = self.header['CRVAL1']

        self.crpix2 = self.header['CRPIX2']
        self.crval2 = self.header['CRVAL2']

        # read projection information
        self.nsgp = self.header['LAM_NSGP']
        self.scale = self.header['LAM_SCAL']
        self.lonpole = self.header['LONPOLE']

    def xyFromSky(self, gLon, gLat):
        """ convert long, lat angles to pixel x y

        input angles are in radians but the conversion assumes radians

        @param [in] gLon galactic longitude in radians

        @param [in] gLat galactic latitude in radians

        @param [out] x is the x pixel coordinate

        @param [out] y is the y pixel coordinate

        """

        rad2deg = 180./numpy.pi

        # use the SFD approach to define xy pixel positions
        # ROTATION - Equn (4) - degenerate case
        if (self.crval2 > 89.9999):
            theta = gLat*rad2deg
            phi = gLon*rad2deg + 180.0 + self.lonpole - self.crval1
        elif (self.crval2 < -89.9999):
            theta = -gLat*rad2deg
            phi = self.lonpole + self.crval1 - gLon*rad2deg
        else:
            # Assume it's an NGP projection ...
            theta = gLat*rad2deg
            phi = gLon*rad2deg + 180.0 + self.lonpole - self.crval1

        # Put phi in the range [0,360) degrees
        phi = phi - 360.0 * numpy.floor(phi/360.0)

        # FORWARD MAP PROJECTION - Equn (26)
        Rtheta = 2.0 * rad2deg * numpy.sin((0.5 / rad2deg) * (90.0 - theta))

        # Equns (10), (11)
        xr = Rtheta * numpy.sin(phi / rad2deg)
        yr = - Rtheta * numpy.cos(phi / rad2deg)

        # SCALE FROM PHYSICAL UNITS - Equn (3) after inverting the matrix
        denom = self.cd11 * self.cd22 - self.cd12 * self.cd21
        x = (self.cd22 * xr - self.cd12 * yr) / denom + (self.crpix1 - 1.0)
        y = (self.cd11 * yr - self.cd21 * xr) / denom + (self.crpix2 - 1.0)

        return x, y

    def generateEbv(self, glon, glat, interpolate = False):
        """
        Calculate EBV with option for interpolation

        @param [in] glon galactic longitude in radians

        @param [in] galactic latitude in radians

        @param [out] ebvVal the scalar value of EBV extinction

        """

        # calculate pixel values
        x, y = self.xyFromSky(glon, glat)

        ix = (x + 0.5).astype(int)
        iy = (y + 0.5).astype(int)

        unity = numpy.ones(len(ix), dtype=int)

        if (interpolate):

            # find the indices of the pixels bounding the point of interest
            ixLow = numpy.minimum(ix, (self.nc - 2)*unity)
            ixHigh = ixLow + 1
            dx = x - ixLow

            iyLow = numpy.minimum(iy, (self.nr - 2)*unity)
            iyHigh = iyLow + 1
            dy = y - iyLow

            # interpolate the EBV value at the point of interest by interpolating
            # first in x and then in y
            x1 = numpy.array([self.data[ii][jj] for (ii, jj) in zip(iyLow, ixLow)])
            x2 = numpy.array([self.data[ii][jj] for (ii, jj) in zip(iyLow, ixHigh)])
            xLow = interp1D(x1, x2, dx)

            x1 = numpy.array([self.data[ii][jj] for (ii, jj) in zip(iyHigh, ixLow)])
            x2 = numpy.array([self.data[ii][jj] for (ii, jj) in zip(iyHigh, ixHigh)])
            xHigh = interp1D(x1, x2, dx)

            ebvVal = interp1D(xLow, xHigh, dy)

        else:
            ebvVal = numpy.array([self.data[ii][jj] for (ii, jj) in zip(iy, ix)])

        return ebvVal

    def xyIntFromSky(self, gLong, gLat):
        x, y = self.xyFromSky(gLong, gLat)
        ix = int(x + 0.5)
        iy = int(y + 0.5)

        return ix, iy


class EBVbase(object):
    """
    This class will give users access to calculateEbv oustide of the framework of a catalog.

    To find the value of EBV at a point on the sky, create an instance of this object, and
    then call calculateEbv passing the coordinates of interest as kwargs

    e.g.

    ebvObject = EBVbase()
    ebvValue = ebvObject.calculateEbv(galacticCoordinates = myGalacticCoordinates)

    or

    ebvValue = ebvObject.calculateEbv(equatorialCoordinates = myEquatorialCoordinates)

    where myGalacticCoordinates is a 2-d numpy array where the first row is galactic longitude
    and the second row is galactic latitude.

    myEquatorialCoordinates is a 2-d numpy array where the first row is RA and the second row
    is dec

    All coordinates are in radians

    You can also specify dust maps in the northern and southern galactic hemispheres, but
    there are default values that the code will automatically load (see the class variables
    below).

    The information regarding where the dust maps are located is stored in
    member variables ebvDataDir, ebvMapNorthName, ebvMapSouthName

    The actual dust maps (when loaded) are stored in ebvMapNorth and ebvMapSouth
    """

    # these variables will tell the mixin where to get the dust maps
    ebvDataDir = os.environ.get("SIMS_MAPS_DIR")
    ebvMapNorthName = "DustMaps/SFD_dust_4096_ngp.fits"
    ebvMapSouthName = "DustMaps/SFD_dust_4096_sgp.fits"
    ebvMapNorth = None
    ebvMapSouth = None

    # A dict to hold every open instance of an EBVmap.
    # Since this is being declared outside of the constructor,
    # it will be a class member, which means that, every time
    # an EBVmap is added to the cache, all EBVBase instances will
    # know about it.
    _ebv_map_cache = {}

    # the set_xxxx routines below will allow the user to point elsewhere for the dust maps
    def set_ebvMapNorth(self, word):
        """
        This allows the user to pick a new northern SFD map file
        """
        self.ebvMapNorthName = word

    def set_ebvMapSouth(self, word):
        """
        This allows the user to pick a new southern SFD map file
        """
        self.ebvMapSouthName = word

    # these routines will load the dust maps for the galactic north and south hemispheres
    def _load_ebv_map(self, file_name):
        """
        Load the EBV map specified by file_name.  If that map has already been loaded,
        just return the map stored in self._ebv_map_cache.  If it must be loaded, store
        it in the cache.
        """
        if file_name in self._ebv_map_cache:
            return self._ebv_map_cache[file_name]

        ebv_map = EBVmap()
        ebv_map.readMapFits(file_name)
        self._ebv_map_cache[file_name] = ebv_map
        return ebv_map

    def load_ebvMapNorth(self):
        """
        This will load the northern SFD map
        """
        file_name = os.path.join(self.ebvDataDir, self.ebvMapNorthName)
        self.ebvMapNorth = self._load_ebv_map(file_name)
        return None

    def load_ebvMapSouth(self):
        """
        This will load the southern SFD map
        """
        file_name = os.path.join(self.ebvDataDir, self.ebvMapSouthName)
        self.ebvMapSouth = self._load_ebv_map(file_name)
        return None

    def calculateEbv(self, galacticCoordinates=None, equatorialCoordinates=None, northMap=None, southMap=None,
                     interp=False):
        """
        For an array of Gal long, lat calculate E(B-V)


        @param [in] galacticCoordinates is a numpy.array; the first row is galactic longitude,
        the second row is galactic latitude in radians

        @param [in] equatorialCoordinates is a numpy.array; the first row is RA, the second row is Dec in
        radians

        @param [in] northMap the northern dust map

        @param [in] southMap the southern dust map

        @param [in] interp is a boolean determining whether or not to interpolate the EBV value

        @param [out] ebv is a list of EBV values for all of the gLon, gLat pairs

        """

        # raise an error if the coordinates are specified in both systems
        if galacticCoordinates is not None:
            if equatorialCoordinates is not None:
                raise RuntimeError("Specified both galacticCoordinates and "
                                   "equatorialCoordinates in calculateEbv")

        # convert (ra,dec) into gLon, gLat
        if galacticCoordinates is None:

            # raise an error if you did not specify ra or dec
            if equatorialCoordinates is None:
                raise RuntimeError("Must specify coordinates in calculateEbv")

            galacticCoordinates = numpy.array(_galacticFromEquatorial(equatorialCoordinates[0, :],
                                                                      equatorialCoordinates[1, :]))

        if northMap is None:
            if self.ebvMapNorth is None:
                self.load_ebvMapNorth()

            northMap = self.ebvMapNorth

        if southMap is None:
            if self.ebvMapSouth is None:
                self.load_ebvMapSouth()

            southMap = self.ebvMapSouth

        ebv = None

        if galacticCoordinates.shape[1] > 0:

            ebv = numpy.zeros(len(galacticCoordinates[0, :]))

            # identify (by index) which points are in the galactic northern hemisphere
            # and which points are in the galactic southern hemisphere
            # taken from
            # http://stackoverflow.com/questions/4578590/python-equivalent-of-filter-getting-two-output-lists-i-e-partition-of-a-list
            inorth, isouth = reduce(lambda x, y: x[not y[1] > 0.0].append(y[0]) or x,
                                    enumerate(galacticCoordinates[1, :]), ([], []))

            nSet = galacticCoordinates[:, inorth]
            sSet = galacticCoordinates[:, isouth]

            ebvNorth = northMap.generateEbv(nSet[0, :], nSet[1, :], interpolate=interp)
            ebvSouth = southMap.generateEbv(sSet[0, :], sSet[1, :], interpolate=interp)

            for (i, ee) in zip(inorth, ebvNorth):
                ebv[i] = ee

            for (i, ee) in zip(isouth, ebvSouth):
                ebv[i] = ee

        return ebv


sims_clean_up.targets.append(EBVbase._ebv_map_cache)
