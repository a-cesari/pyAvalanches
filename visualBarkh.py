import scipy
import scipy.ndimage as nd
import scipy.signal as signal
import scipy.stats.stats
import scikits.image.io as im_io
import numpy as np
import numpy.ma as ma
import Image, ImageDraw
import os, sys, glob
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from scikits.image.filter import tv_denoise
import tables
import time
import getLogDistributions as gLD
reload(gLD)
import getAxyLabels as gAL
reload(gAL)

filters = {'gauss': nd.gaussian_filter, 'fouriergauss': nd.fourier_gaussian, \
           'median': nd.median_filter, 'tv': tv_denoise, 'wiener': signal.wiener}

im_io.use_plugin('qt', 'imshow')

def imread_convert(f):
    return im_io.imread(f).astype(np.int16)

class StackImages:
    """
    Load and analyze a sequence of images 
    as a multi-dimensional scipy 3D array.
    The k-th element of the array (i.e. myArray[k])
    is the k-th image of the sequence.
    """
        
    def __init__(self,mainDir,filtering="Gauss",sigma=2,resize_factor=None,\
                 mountDir="/home/gf/meas/",fileType=None,imageFirst=0,imageLast=-1):
        self.colorImage = None
        self.koreanPalette = None
        self.colorImageDone = False
        self.threshold = 0
        self.figTimeSeq = None
        self.figDiffs = None
        if imageLast == None:
            imageLast = -1
        # Make a kernel as a step-function
        self.kernel = np.array([-1]*(5) +[1]*(5)) # Good for Black_to_White change of grey scale
        self.kernel0 = np.array([-1]*(5) +[0] + [1]*(5)) 
        if not fileType:
            # Check if ~/meas is mounted or existing
            who = os.getlogin()
            if who == 'gf':
                mountDir = os.path.join("/home", who, "meas")
                if not os.path.ismount(mountDir) and not os.path.isdir(mainDir):
                    print "Please mount dir ", mountDir
                    sys.exit()
            # Collect the list of images in mainDir
            extSeq = ['tif','jpg','jpeg','ppm']
            for ext in extSeq:
                dirImages = os.path.join(mainDir,"*."+ext)
                imageFileNames = sorted(glob.glob(dirImages))
                if len(imageFileNames):
                    print "Found %d images to load in %s" % (len(imageFileNames), mainDir)
                    print "First image: %s" % os.path.split(imageFileNames[imageFirst])[1]
                    print "Last image: %s" % os.path.split(imageFileNames[imageLast])[1]
                    break
            if not len(imageFileNames):    
                print "Warning, no images in %s" % mainDir
                sys.exit()
    
            # Load the images
            print "Loading images: "
            load_pattern = imageFileNames[imageFirst:imageLast]
            imageCollection = im_io.ImageCollection(load_pattern, load_func=imread_convert)
            if filtering:
                filtering = filtering.lower()
                if filtering not in filters:
                    print "Filter not available"
                    sys.exit()
                else:
                    print "Filter: %s" % filtering
                    if filtering == 'wiener':
                        sigma = [sigma, sigma]
                    self.Array = np.dstack([np.int16(filters[filtering](im,sigma)) for im in imageCollection])
            else:
                self.Array = np.dstack([im for im in imageCollection])
            # Check for the grey direction
            grey_first_image = scipy.mean(self.Array[:,:,0].flatten())
            grey_last_image = scipy.mean(self.Array[:,:,-1].flatten())
            print "grey scale: %i, %i" % (grey_first_image, grey_last_image)
            if grey_first_image > grey_last_image:
                self.kernel = -self.kernel
                self.kernel0 = -self.kernel0
        elif fileType=="hdf5":
            self.hdf5 = tables.openFile("/home/gf/meas/Barkh/Film_CoFe.h5",'a')
            self.imagesObj = self.hdf5.root.tk_20nm.mg_20x.run_15.dir_down.im_Gauss25
            self.Array = self.imagesObj.read()
            if self.imagesObj._v_attrs.GREY_DIRECTION == "White_to_black":
                self.kernel = [-k for k in self.kernel]
            self.imageDir = self.imagesObj._v_attrs.IMAGE_DIRECTION
            #hdf5.close()
        self.dimX, self.dimY, self.n_images = self.Array.shape
        print "%i image(s) loaded, of %i x %i pixels" % (self.n_images, self.dimX, self.dimY)
        
    def __get__(self):
        return self.Array
        
    def __getitem__(self,i):
        "Get the i-th image"
        return self.Array[:,:,i]
        
    def imShow(self, frame_number):
        """
        imShow(frame_number)
        
        Show the i-th image where i = frame_number
        
        Parameters:
        ---------------
        frame_number : number, int
            Number of the frame to be shown.
        """
        if frame_number > self.n_images or frame_number < 0:
            print "index out of range (0,%i)" % n_images-1
            return
        im_io.imshow(self[frame_number])
        
    def _getLevels(self, pxTimeSeq, switch, kernel='step'):
        """
        _getLevels(pxTimeSeq, switch, kernel='step')
        
        Internal function to calculate the gray level before and 
        after the switch of a sequence, using the kernel 
        
        Parameters:
        ---------------
        pxTimeSeq : list
            The sequence of the gray level for a given pixel.
        switch : number, int
            the position of the switch as calculated by getSwitchTime
        kernel : 'step' or 'zero'
           the kernel of the step function

        Returns:
        -----------
        levels : tuple
           Left and right levels around the switch position
        """
        try:
            width = self.width
        except:
            width = 'all'
            print("Warning: the levels are calculated over all the points of the sequence")
        # Get points before the switch
        if width == 'small': 
            halfWidth = len(self.kernel)/2
            lowPoint = switch - halfWidth - 1*(kernel=='zero')
            if lowPoint < 0:
                lowPoint = 0
            highPoint = switch + halfWidth
            if highPoint > len(pxTimeSeq):
                highPoint = len(pxTimeSeq)
        elif width == 'all':
            lowPoint, highPoint = 0, len(pxTimeSeq)
        else:
            print 'Method not implement yet'
            return None
        leftLevel = np.int(np.mean(pxTimeSeq[lowPoint:switch - 1*(kernel=='zero')])+0.5)
        rigthLevel = np.int(np.mean(pxTimeSeq[switch:highPoint])+0.5)
        levels = leftLevel, rigthLevel 
        return levels
    
    
    def pixelTimeSequence(self,pixel=(0,0)):
        """
        pixelTimeSequence(pixel)
        
        Returns the temporal sequence of the gray level of a pixel
        
        Parameters:
        ---------------
        pixel : tuple
           The (x,y) pixel of the image, as (row, column)
        """
        x,y = pixel
        return self.Array[x,y,:]
        
    def pixelTimeSequenceShow(self,pixel=(0,0),newPlot=False):
        """
        pixelTimeSequenceShow(pixel)
        
        Plot the temporal sequence of the gray levels of a pixel;
        
        Parameters:
        ---------------
        pixel : tuple
            The (x,y) pixel of the image, as (row, column)
        newPlot : bool
            Option to open a new frame or use the last one
        """
        try:
            width = self.width
        except:
            width = 'all'
            print("Warning: the levels are calculated over all the points of the sequence")
        # Plot the temporal sequence first
        pxt = self.pixelTimeSequence(pixel)
        if not self.figTimeSeq or newPlot==True:
            self.figTimeSeq = plt.figure()
        else:
            self.figTimeSeq
        plt.plot(pxt,'-o')
        # Add the two kernels function
        kernels = [self.kernel, self.kernel0]
        for k,kernel in enumerate(['step','zero']):	
            switch, (value_left, value_right) = self.getSwitchTime(pixel,useKernel=kernel)
            print "switch %s, Kernel = %s" % (kernel, switch)
            print ("gray level change at switch = %s") % abs(value_left-value_right)
            if width == 'small':
                halfWidth = len(kernels[k])/2
                x = range(switch - halfWidth - 1*(k==1), switch + halfWidth)
                n_points_left = halfWidth
                n_points_rigth = halfWidth
            elif width=='all':
                x = range(len(pxt))
                n_points_left = switch - 1 * (k==1)
                n_points_rigth = len(pxt) - switch
            y = n_points_left * [value_left] + [(value_left+value_right)/2.] * (k==1) + n_points_rigth * [value_right]
            plt.plot(x,y)
        plt.draw()
        plt.show()
        
    def getSwitchTime(self, pixel=(0,0), useKernel='step', method='convolve1d'):
        """
        getSwitchTime(pixel, useKernel='step', method="convolve1d")
        
        Return the position of a step in a sequence
        and the left and the right values of the gray level (as a tuple)
        
        Parameters:
        ---------------
        pixel : tuple
            The (x,y) pixel of the image, as (row, column).
        useKernel : string
            step = [1]*5 +[-1]*5
            zero = [1]*5 +[0] + [-1]*5
            both = step & zero, the one with the highest convolution is chosen
        method : string
            For the moment, only the 1D convolution calculation
            with scipy.ndimage.convolve1d
        """
        startTime = time.time()
        pxTimeSeq = self.pixelTimeSequence(pixel)
        if method == "convolve1d":
            if useKernel == 'step' or useKernel == 'both':
                convolution_of_stepKernel = nd.convolve1d(pxTimeSeq,self.kernel)
                minStepKernel = convolution_of_stepKernel.min()
                switchStepKernel = convolution_of_stepKernel.argmin() +1
                switch = switchStepKernel
                kernel_to_use = 'step'
            if useKernel == 'zero' or useKernel == 'both':
                convolution_of_zeroKernel = nd.convolve1d(pxTimeSeq,self.kernel0)
                minZeroKernel = convolution_of_zeroKernel.min()
                switchZeroKernel = convolution_of_zeroKernel.argmin() + 1
                switch = switchZeroKernel
                kernel_to_use = 'zero'
            if useKernel == 'both':
                if minStepKernel <= minZeroKernel:
                    switch = switchStepKernel
                    kernel_to_use = 'step'
                else:
                    switch = switchZeroKernel
                    kernel_to_use = 'zero'
                    #leftLevel = np.int(np.mean(pxTimeSeq[0:switch])+0.5)
                    #rightLevel = np.int(np.mean(pxTimeSeq[switch+1:])+0.5)
                    #middle = (leftLevel+rightLevel)/2
                    #rightLevelStep = np.int(np.mean(pxTimeSeq[switchStepKernel+1:])+0.5)
                    #if abs(pxTimeSeq[switch]-middle)>abs(pxTimeSeq[switch]-rightLevelStep):
                        #switch = switchStepKernel                    
                    #switch = (switch-1)*(pxTimeSeq[switch]<middle)+switch*(pxTimeSeq[switch]>=middle)
                #switch = switchStepKernel * (minStepKernel<=minZeroKernel/1.1) + switchZeroKernel * (minStepKernel >minZeroKernel/1.1)
        else:
            raise RuntimeError("Method not yet implemented")            
        levels = self._getLevels(pxTimeSeq, switch, kernel_to_use) 
        return switch, levels

    def imDiff(self,i,j=0):
        "Properly rescaled difference between images"
        im = self[i]-self[j]
        imMin = scipy.amin(im)
        imMax = scipy.amax(im)
        im = scipy.absolute(im-imMin)/float(imMax-imMin)*255
        return scipy.array(im,dtype='int16')

    def imDiffShow(self,i,j):
        "Show a properly rescale difference between images"
        plt.imshow(self.imDiff(i,j),plt.cm.gray)
        
    def imDiffSave(self,mainDir):
        dirSeq = os.path.join(mainDir,"Seq")
        if not os.path.isdir(dirSeq):
            os.mkdir(dirSeq)
        n = self.n_images
        for i in range(n-1):
            im = self.imDiff(i+1,i)
            imPIL = scipy.misc.toimage(im)
            fileName = "imDiff_%i_%i.tif" % (i+1,i)
            imageFileName = os.path.join(dirSeq, fileName)
            imPIL.save(imageFileName)
        

    def contrastStretching(self,imageNum,val_1,val_2,relative=False):
        """
        Apply contrast Stretching
        to a single image
        as suggested on DigitalImageProcessing, page. 85
        """
        im = self[imageNum]
        imOut = 0
        if relative:
            k = 255
        else:
            k = 1
        r1,s1 = int(val_1[0]*k), int(val_1[1]*k)
        r2,s2 = int(val_2[0]*k), int(val_2[1]*k)
        lt = scipy.less(im,r1+1)
        if r1 != 0:
            imOut += lt*im*s1/r1
        bw = scipy.greater_equal(im,r1) & scipy.less_equal(im,r2)
        if r2!=r1:
            imOut += bw*((im-r1)/float(r2-r1)*(s2-s1)+s1)
        gt = scipy.greater(im,r2)
        if r2!= 255:
            imOut += gt*((im-r2)/(255.-r2)*(255.-s2)+s2)  
        return imOut

    def histogramEqualization(self,im):
        """
        Perform the histogram equalization on the image or an array;
        returns an array
        """
        if not isinstance(im, type(np.array([]))):
            im = np.array(im)
        histOut = scipy.histogram(im.flat, range(257),normed=True)
        cdf = scipy.cumsum(histOut[0])*255
        return scipy.array(cdf[im], dtype='int16')

    
    def histogramEqualizationSequence(self):
        """
        Perform the histogram equalization on all images
        of a sequence; returns a 3D array
        """
        seqImages = []
        for i in range(self.n_images):
            im = self[i]
            imOut = histogramEqualization(im)
            seqImages.append(imOut)
        return scipy.array(tuple(seqImages))
            
    def shape(self):
        return self.Array.shape
    
    def getSwitchTimesAndSteps(self):
        """
        Calculate the switch times and the gray level changes
        for each pixel in the image sequence
        """
        self.switchTimes = []
        self.switchSteps = []
        noSwitch = False
        startTime = time.time()
        # ####################
        # TODO: make here a parallel calculus
        for x in range(self.dimX):
            # Print current row
            if not (x+1)%10:
                strOut = 'Analysing row:  %i/%i on %f seconds\r' % (x+1, self.dimX, time.time()-startTime)
                sys.stdout.write(strOut)
                sys.stdout.flush()
                startTime = time.time()
            for y in range(self.dimY):
                switch, levels = self.getSwitchTime((x,y))
                grayChange = np.abs(levels[0]- levels[1])
                if switch == 0: # TODO: how to deal with steps at zero time
                    print x,y
                self.switchTimes.append(switch)
                self.switchSteps.append(grayChange)
        print "\n"
        self.colorImageDone = True
        return

    def getKoreanColors(self,switchTime,n_images=None):
        """
        Make a palette in the korean style
        """
        if not n_images:
            n_images = self.n_images
        n = float(switchTime)/float(n_images)*3.
        R = (n<=1.)+ (2.-n)*(n>1.)*(n<=2.)
        G = n*(n<=1.)+ (n>1.)*(n<=2.)+(3.-n)*(n>2.)
        B = (n-1.)*(n>=1.)*(n<2.)+(n>=2.)
        R, G, B = [int(i*255) for i in [R,G,B]]
        return R,G,B
    
    def checkColorImageDone(self,ask=True):
        print "You must first run the getSwitchTimesAndSteps script: I'll do that for you"
        if ask:
            yes_no = raw_input("Do you want me to run the script for you (y/N)?")
            yes_no = yes_no.upper()
            if yes_no != "Y":
                return
        self.getSwitchTimesAndSteps()
        return

    def getColorImage(self,threshold=None, palette='korean',noSwitchColor='black'):
        """
        Calculate the color Image using the output of getSwitchTimesAndSteps
        """
        if not threshold:
            threshold = 0
        if not self.colorImageDone:
            self.checkColorImageDone(ask=False)

        # Calculate the colours, considering the range of the switch values obtained 
        if self.koreanPalette is None:
            self.min_switch = np.min(self.switchTimes)
            self.max_switch = np.max(self.switchTimes)
            print "Avalanches occur between frame %i and %i" % (self.min_switch, self.max_switch)
            nImagesWithSwitch = self.max_switch - self.min_switch+1
            print "Gray changes are between %s and %s" % (min(self.switchSteps), max(self.switchSteps))
            # Prepare the Korean Palette
            self.koreanPalette = np.array([self.getKoreanColors(i-self.min_switch, nImagesWithSwitch) for i in range(self.min_switch,self.max_switch+1)])            
            
        if palette == 'korean':
            pColor = self.koreanPalette
        elif palette == 'randomKorean':
            pColor = np.random.permutation(self.koreanPalette)
        elif palette == 'random':
            pColor = np.random.randint(0,256, self.koreanPalette.shape)
        if noSwitchColor == 'black':
            noSwitchColorValue = [0,0,0]
        elif noSwitchColor == 'white':
            noSwitchColorValue = [255, 255, 255]
        pColor = np.concatenate((pColor, [noSwitchColorValue]))
        self.switchTimesArray = self._getSwitchTimesArray(threshold, True, -1)
        # Get the color from the palette and reshape to get the image
        return pColor[self.switchTimesArray].reshape(self.dimX, self.dimY, 3)

    def _getSwitchTimesArray(self, threshold=0, isFirstSwitchZero=False, fillValue=-1):
        """
        _getSwitchTimesArray(threshold=0)
        
        Returns the array of the switch times
        considering a threshold in the gray level change at the switch
        
        Parameters:
        ----------------
        threshold : int
            The miminum value of the gray level change at the switch
        isFirstSwitchZero : bool
            Put the first switch equal to zero, useful to set the colors 
            in a long sequence of images where the first avalanche 
            occurs after many frames
        fillValue : number, int
            The value to set in the array for the non-switching pixel (below the threshold)
            -1 is use as the last value of array when use as index (i.e. with colors)
        """
        if not threshold:
            threshold = 0
        self.isPixelSwitched = scipy.array(self.switchSteps) >= threshold    
        maskedSwitchTimes = ma.array(self.switchTimes, mask = ~self.isPixelSwitched)
        # Move to the first switch time if required
        if isFirstSwitchZero:
            maskedSwitchTimes = maskedSwitchTimes - self.min_switch
        # Set the non-switched pixels to use the last value of the pColor array, i.e. noSwitchColorValue
        switchTimesArray = maskedSwitchTimes.filled(fillValue) # Isn't it fantastic?
        return switchTimesArray
    
    def showColorImage(self,threshold=None, palette='random',noSwitchColor='black',ask=False):
        """
        showColorImage([threshold=None, palette='random', noSwitchColor='black', ask=False])
        
        Show the calculated color Image of the avalanches.
        Run getSwitchTimesAndSteps if not done before.
        
        Parameters
        ---------------
        threshold: integer, optional
            Defines if the pixel switches when gray_level_change >= threshold
        palette: string, required, default = 'korean'
            Choose a palette between 'korean', 'randomKorean', and 'random'
            'randomKorean' is a random permutation of the korean palette
            'random' is calculated on the fly, so each call of the method gives different colors
        noSwithColor: string, optional, default = 'black'
            background color for pixels having gra_level_change below the threshold
            
        """
        self.colorImage = self.getColorImage(threshold, palette, noSwitchColor)
        #imOut = scipy.misc.toimage(self.colorImage)
        #imOut.show()
        plt.imshow(self.colorImage)
        # Count the number of the switched pixels
        switchPixels = np.sum(self.isPixelSwitched)
        totNumPixels = self.dimX*self.dimY
        noSwitchPixels = totNumPixels - switchPixels
        swPrint = (switchPixels, switchPixels/float(totNumPixels)*100., noSwitchPixels, noSwitchPixels/float(totNumPixels)*100.)
        print "There are %d (%.2f %%) switched and %d (%.2f %%) not-switched pixels" % swPrint
        yes_no = raw_input("Do you want to save the image (y/N)?")
        yes_no = yes_no.upper()
        if yes_no == "Y":
            fileName = raw_input("Filename (ext=png): ")
            if len(fileName.split("."))==1:
                fileName = fileName+".png"
            fileName = os.path.join(mainDir,fileName)
            imOut = scipy.misc.toimage(self.colorImage)
            imOut.save(fileName)

    def saveColorImage(self,fileName,threshold=None, palette='korean',noSwitchColor='black'):
        """
        saveColorImage(fileName, threshold=None, palette='korean',noSwitchColor='black')
        
        makes color image and saves
        """
        self.colorImage = self.getColorImage(threshold, palette,noSwitchColor)
        imOut = scipy.misc.toimage(self.colorImage)
        imOut.save(fileName)
            
    def imDiffCalculated(self,imageNum,haveColors=True):
        """
        Get the difference in BW between two images imageNum and imageNum+1
        as calculated by the self.colorImage
        """
        if not self.colorImageDone:
            self.checkColorImageDone(ask=False)
        imDC = (self.switchTimesArray==imageNum)*1
        if haveColors:
            imDC = scipy.array(imDC,dtype='int16')
            structure = [[0, 1, 0], [1,1,1], [0,1,0]]
            l, n = nd.label(imDC,structure)
            im_io.imshow(l,plt.cm.prism)
        else:
            # Normalize to a BW image
            self.imDiffCalcArray = imDC*255
            scipy.misc.toimage(self.imDiffCalcArray).show()
        return None
    
    def _getImageDirection(self, threshold=None):
        """
        _getImageDirection(threshold=None)
        
        Returns the direction of the sequence of avalanches as: 
        "Top_to_bottom","Left_to_right", "Bottom_to_top","Right_to_left"
        
        Parameters:
        ----------------
        threshold : int
            Minimum value of the gray level change to conisider
            a pixel as part of an avalanche (i.e. it is switched)
        """
        if not self.colorImageDone:
            self.checkColorImageDone(ask=False)
        dims = self.dimX, self.dimY
        _switchTimesArray = self._getSwitchTimesArray(threshold, False, 0)
        switchTimesMasked = _switchTimesArray.reshape(dims)
        pixelsUnderMasks = []
        # first identify first/last 10 avalanches of whole image
        avsList = sorted(set(_switchTimesArray))
        if avsList[0] == 0: # some pixels did not switch
            first = 1
        else:
            first = 0
        firstAvsList = avsList[first:11]
        lastAvsList = avsList[-10:]
        # Prepare the mask
        m = np.ones((self.dimX,self.dimY))
        # Top mask
        mask = np.rot90(np.triu(m))*np.triu(m)
        top = switchTimesMasked*mask
        pixelsUnderMasks.append(sum([np.sum(top==elem) for elem in firstAvsList]))
        # Now we need to rotate the mask
        for i in range(3):
            mask = np.rot90(mask)
            top = switchTimesMasked*mask
            pixelsUnderMasks.append(sum([np.sum(top==elem) for elem in firstAvsList]))
        # Top, left, bottom, rigth
        imageDirections=["Top_to_bottom","Left_to_right", "Bottom_to_top","Right_to_left"]
        max_in_mask = scipy.array(pixelsUnderMasks).argmax()
        print(imageDirections[max_in_mask])
        return imageDirections[max_in_mask]
    
    
    def getDistributions(self,threshold=3,NN=4,log_step=0.2,edgeThickness=1):
        #Define the numer of nearest neighbourg
        if NN==8:
            structure = [[1, 1, 1], [1,1,1], [1,1,1]]
        else:
            structure = [[0, 1, 0], [1,1,1], [0,1,0]]
            if NN!=4:
                print "N. of neibourgh not valid: assuming NN=4"
        # Check if analysis of avalanches has been performed
        if not self.colorImageDone:
            self.checkColorImageDone(ask=False)
        # Select the images having swithing pixels
        # and initialize the distributions
        self.switchTimesArray = np.array(self.switchTimes).reshape((self.dimX, self.dimY))
        n_max = max(self.switchTimes)
        n_min = min(self.switchTimes)
        #self.imageDir = self.getImageDirection(threshold)
        self.imageDir = "Left_to_right"
        self.D_avalanches = []
        self.D_cluster = scipy.array([], dtype='int32')
        self.N_cluster = []
        self.dictAxy = {}
        a0 = scipy.array([],dtype='int32')
        #
        # Make a loop to calculate avalanche and clusters for each image
        #
        for imageNum in range(n_min,n_max+1): 
            strOut = 'Analysing image n:  %i\r' % imageNum
            sys.stdout.write(strOut)
            sys.stdout.flush()
            # Select the pixel flipped at the imageNum
            im0 = (self.switchTimesArray==imageNum)*1
            im0 = scipy.array(im0,dtype="int16")
            # Update the list of sizes of the global avalanche (i.e. for the entire image n. imageNum)
            self.D_avalanches.append(scipy.sum(im0))
            # Detect local clusters using scipy.ndimage method
            array_labels, n_labels = nd.label(im0,structure)
            # Make a list the sizes of the clusters
            list_sizes = nd.sum(im0,array_labels,range(1,n_labels+1))
            # Prepare the distributions
            self.D_cluster = scipy.concatenate((self.D_cluster,list_sizes))
            self.N_cluster.append(n_labels)
            # Now find the Axy distributions (A00, A10, etc)
            # First make an array of the edges each cluster touches
            array_Axy = gAL.getAxyLabels(array_labels,self.imageDir,edgeThickness)
            # Note: we can restrict the choice to left and right edges (case of strip) using:
            # array_Axy = [s[:2] for s in array_Axy]
            # Now select each type of cluster ('0000', '0010', etc), make the S*P(S), and calculate the distribution
            array_sizes = scipy.array(list_sizes,dtype='int32')
            for Axy in set(array_Axy):
                sizes = array_sizes[array_Axy==Axy] # Not bad...
                self.dictAxy[Axy] = scipy.concatenate((self.dictAxy.get(Axy,a0),sizes))

        # Calculate and plot the distributions of clusters and avalanches
        D_x, D_y = gLD.logDistribution(self.D_cluster,log_step=log_step,first_point=1.,normed=True)
        P_x, P_y = gLD.logDistribution(self.D_avalanches,log_step=log_step,first_point=1.,normed=True)
        # Plots of the distributions
        plt.figure()
        plt.loglog(D_x,D_y,'o', label='cluster')
        plt.loglog(P_x,P_y,'v',label='avalanches')
        plt.legend()
        plt.show()
        # Show the N_clusters vs. size_of_avalanche
        plt.figure()
        plt.loglog(self.D_avalanches,self.N_cluster,'o')
        plt.xlabel("Avalanche size")
        plt.ylabel("N. of clusters")
        plt.show()

    def compareImages(self, n, threshold=0):
        if n in self.switchTimes:
            out = self._getSwitchTimesArray(threshold, fillValue=0).reshape(self.dimX, self.dimY)
            fig = plt.figure()
            fig.set_size_inches(12,6,forward=True)
            plt.subplot(1,2,1)
            plt.imshow(self.imDiff(n,n-1),plt.cm.gray)
            plt.title("Fig. %s, Original" % n)
            plt.grid(color='blue', ls="-")
            plt.subplot(1,2,2)
            plt.imshow(out == n, plt.cm.gray)
            plt.title("Fig. %s, Calculated" % n)
            plt.grid(color='blue',ls="-")
        else:
            print "No switch there"
        return

        
    def getDictOfColors(self,outPixels):
        d = {}
        for c in outPixels:
            d[c] = d.get(c,0) +1
        return d


    def getWindowDistributions(self):
        """
        classify windowed avs according to switch times, this outputs distribution for each run
        """
        switchTimesList = self.switchTimes	
        avs_list = set(switchTimesList)
        switchTimesArray = switchTimesList.reshape((500,500)) # reshape array into (x,y) 
        
        for n_av in avs_list:
            single_av = (switchTimesArray==n_avs)*1
            area = np.sum(single_av)
            height = max(np.sum(single_av, axis=0))
            width = max(np.sum(single_av,axis=1))
            
            if area in A_s.keys():
                A_s[area]+=area
            else:
                A_s[area] = area
                
            
        # determine how many boundaries each avalanche touches to classify
    

if __name__ == "__main__":
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/50nm/run2/"
    # Select dir for analysis: TO IMPROVE
    #mainDir = "/home/gf/meas/Baxrkh/Films/CoFe/20nm/run3_50x/down/"
    #mainDir = "/home/gf/meas/Barkh/Films/FeBSi/50nm/run1/down"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/run1_20x/down"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/run9_20x_5ms"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/run10_20x_bin1"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/run11_20x_bin1_contrast_diff"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/run15_20x_save_to_memory/down"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/run32"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/good set 2/run5/"
    #mainDir = "/home/gf/meas/MO/py170/20x/set7"
    #mainDir = "/home/gf/Misure/Alex/Zigzag/samespot/run2"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/run22_50x_just_rough/down"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/run23_50x_rough_long"
    #mainDir = "/home/gf/meas/Simulation"
    #mainDir = "/media/DATA/meas/MO/CoFe 20 nm/10x/good set 2/run7"
    ##mainDir = "/media/DATA/meas/MO/CoFe 20 nm/5x/set1/run1/"
    #mainDir = "/home/gf/meas/Barkh/Films/CoFe/20nm/10x/good set 2/run8/"
    mainDir = "/home/gf/meas/Barkh/Films/CoFe/50nm/run2/"
    firstImage = 0
    lastImage = None
    imArray = StackImages(mainDir,filtering='wiener',sigma=1.,resize_factor=False,fileType=None,\
                    imageFirst=firstImage, imageLast=lastImage)

    imArray.width='small'
    imArray.useKernel = 'step'
