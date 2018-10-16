from __future__ import print_function
from builtins import range
import os
import numpy as np
import warnings

import lsst.utils
from .matchUtils import matchStar
from .BandpassDict import BandpassDict
from .EBV import EBVbase as ebv

__all__ = ["selectStarSED"]

class selectStarSED(matchStar):

    """
    This class provides a way to match star catalog magntiudes to those of the approriate SED.
    """

    def findSED(self, sedList, catMags, catRA = None, catDec = None, mag_error = None,
                reddening = True, bandpassDict = None, colors = None, nullValues = None,
                extCoeffs = (4.239, 3.303, 2.285, 1.698, 1.263), makeCopy = False, verbose=True):

        """
        This will find the SEDs that are the closest match to the magnitudes of a star catalog.
        It can also correct for reddening from within the milky way. Objects without magnitudes in at least
        two adjacent bandpasses will return as none and print out a message.

        @param [in] sedList is the set of spectral objects from the models SEDs provided by loaders in rgStar
        in rgUtils.py or other custom loader routine.

        @param [in] catMags is an array of the magnitudes of catalog objects to be matched with a model SED.
        It should be organized so that there is one object's magnitudes along each row.

        @param [in] catRA is an array of the RA positions for each catalog object.

        @param [in] catDec is an array of the Dec position for each catalog object.

        @param [in] mag_error are provided error values for magnitudes in objectMags. If none provided
        then this defaults to 1.0. This should be an array of the same length as objectMags.

        @param [in] reddening is a boolean that determines whether to correct catalog magnitudes for
        dust in the milky way. By default, it is True.
        If true, this uses calculateEBV from EBV.py to find an EBV value for the object's
        ra and dec coordinates and then uses the coefficients provided by extCoeffs which should come
        from Schlafly and Finkbeiner (2011) for the correct filters and in the same order as provided
        in bandpassDict.
        If false, this means it will not run the dereddening procedure.

        @param [in] bandpassDict is a BandpassDict with which to calculate magnitudes. If left
        equal to None it will by default load the SDSS [u,g,r,i,z] bandpasses and therefore agree with
        default extCoeffs.

        @param [in] colors is None if you are just providing a list of SED objects to match, but is the
        array holding the colors of those SED models (each row should be the colors for one model in the
        same order as sedList) if you have already calculated the colors.

        @param [in] nullValues is None by default. This means that your catalog is complete and there is no
        default value in your catalog for missing data. If you do have a number that indicates missing data
        then set this parameter to that value and these missing values will be ignored when matching colors.

        @param [in] extCoeffs are the Schlafly and Finkbeiner (2011) (ApJ, 737, 103)  coefficients for the
        given filters from bandpassDict and need to be in the same order as bandpassDict. The default given
        are the SDSS [u,g,r,i,z] values.

        @param [in] makeCopy indicates whether or not to operate on copies of the SED objects in sedList
        since this method will change the wavelength grid.

        @param [out] sedMatches is a list with the name of a model SED that matches most closely to each
        object in the catalog.

        @param [out] magNormMatches are the magnitude normalizations for the given magnitudes and
        matched SED.

        @param [out] matchErrors contains the Mean Squared Error between the colors of each object and
        the colors of the matched SED.
        """

        if bandpassDict is None:
            starPhot = BandpassDict.loadTotalBandpassesFromFiles(['u','g','r','i','z'],
                                            bandpassDir = os.path.join(lsst.utils.getPackageDir('throughputs'),
                                                                       'sdss'),
                                            bandpassRoot = 'sdss_')
        else:
            starPhot = bandpassDict

        if colors is None:
            modelColors = self.calcBasicColors(sedList, starPhot, makeCopy=makeCopy)
        else:
            modelColors = colors
        #Transpose so that all values for one color are in one row as needed for the matching loop below
        modelColors = np.transpose(modelColors)

        #Set null values to nan so that we will skip them below
        if nullValues is not None:
            catMags[np.where(catMags == nullValues)] = np.nan

        if reddening == True:
            #Check that catRA and catDec are included
            if catRA is None or catDec is None:
                raise RuntimeError("Reddening is True, but catRA and catDec are not included.")
            calcEBV = ebv()
            raDec = np.array((catRA,catDec))
            #If only matching one object need to reshape for calculateEbv
            if len(raDec.shape) == 1:
                raDec = raDec.reshape((2,1))
            ebvVals = calcEBV.calculateEbv(equatorialCoordinates = raDec)
            objMags = self.deReddenMags(ebvVals, catMags, extCoeffs)
        else:
            objMags = catMags

        objMags = np.array(objMags)
        matchColors = []

        for filtNum in range(0, len(starPhot)-1):
            matchColors.append(np.transpose(objMags)[filtNum] - np.transpose(objMags)[filtNum+1])

        matchColors = np.transpose(matchColors)

        numCatMags = len(catMags)
        numOn = 0
        sedMatches = []
        magNormMatches = []
        notMatched = 0
        matchErrors = []

        for catObject in matchColors:
            #This is done to handle objects with incomplete magnitude data
            colorRange = np.arange(0, len(starPhot)-1)
            filtNums = np.arange(0, len(starPhot))
            if np.isnan(np.amin(catObject))==True:
                colorRange = np.where(np.isnan(catObject)==False)[0]
                filtNums = np.unique([colorRange, colorRange+1]) #Pick right filters in calcMagNorm
            if len(colorRange) == 0:
                if verbose == True:
                    print('Could not match object #%i. No magnitudes for two adjacent bandpasses.' % (numOn))
                notMatched += 1
                sedMatches.append(None)
                magNormMatches.append(None)
                matchErrors.append(None)
            else:
                distanceArray = np.zeros(len(sedList))
                for colorNum in colorRange:
                    distanceArray += np.power((modelColors[colorNum] - catObject[colorNum]),2)
                matchedSEDNum = np.nanargmin(distanceArray)
                sedMatches.append(sedList[matchedSEDNum].name)
                magNorm = self.calcMagNorm(objMags[numOn], sedList[matchedSEDNum],
                                           starPhot, filtRange = filtNums)
                magNormMatches.append(magNorm)
                matchErrors.append(distanceArray[matchedSEDNum]/len(colorRange)) #Mean Squared Error
            numOn += 1
            if numOn % 10000 == 0:
                print('Matched %i of %i catalog objects to SEDs' % (numOn-notMatched, numCatMags))
        if numCatMags > 1:
            print('Done Matching. Matched %i of %i catalog objects to SEDs' % (numCatMags-notMatched,
                                                                               numCatMags))
        if notMatched > 0:
            print('%i objects did not get matched' % (notMatched))

        return sedMatches, magNormMatches, matchErrors
