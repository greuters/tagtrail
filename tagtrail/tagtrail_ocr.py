#  tagtrail: A bundle of tools to organize a minimal-cost, trust-based and thus
#  time efficient accounting system for small, self-service community stores.
#
#  Copyright (C) 2019, Simon Greuter
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.
import argparse
import cv2 as cv
import numpy as np
import itertools
import pytesseract
import PIL
import os
import math
import Levenshtein
import slugify
from abc import ABC, abstractmethod
import helpers
from sheets import ProductSheet
from database import Database
from os import walk

class ProcessingStep(ABC):
    def __init__(self,
            name,
            outputDir = 'data/tmp/',
            log = helpers.Log()):
        self._name = name
        self._log = log
        self._outputDir = outputDir
        super().__init__()

    @property
    def prefix(self):
        return f'{self._outputDir}{self._name}'

    @abstractmethod
    def process(self, inputImg):
        self._log.info("#ProcessStep: {}".format(self._name))
        self._outputImg = inputImg

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}.jpg', self._outputImg)

class LineBasedStep(ProcessingStep):
    drawLineLength = 1000

    @abstractmethod
    def process(self, inputImg):
        super().process(inputImg)
        self._linesImg = inputImg

    # pt0 = (x0, y0)
    # v0 = (dx, dy)
    def ptAndVecToPts(self, p0, v0):
        x0, y0 = p0
        dx, dy = v0
        return ((int(x0-self.drawLineLength*dx), int(y0-self.drawLineLength*dy)),
                (int(x0+self.drawLineLength*dx), int(y0+self.drawLineLength*dy)))

    # computes the minimal rotation angle [rad] necessary to make the line either
    # horizontal or vertical
    def minAngleToGridPts(self, pt0, pt1):
        x0, y0 = pt0
        x1, y1 = pt1
        if x0==x1 or y0==y1:
            return 0
        if x0<x1 and y0<y1:
            alpha = np.arctan((y1-y0) / (x1-x0))
            if alpha > np.pi/4: alpha = alpha - np.pi/2
        if x0<x1 and y0>y1:
            alpha = np.arctan((x1-x0) / (y0-y1))
            if alpha > np.pi/4: alpha = alpha - np.pi/2
        if x0>x1 and y0<y1:
            alpha = np.arctan((x0-x1) / (y1-y0))
            if alpha > np.pi/4: alpha = alpha - np.pi/2
        if x0>x1 and y0>y1:
            alpha = np.arctan((y0-y1) / (x0-x1))
            if alpha > np.pi/4: alpha = alpha - np.pi/2
        return alpha

    def minAngleToGridPtAndVec(self, pt0, v0):
        (pt0, pt1) = self.ptAndVecToPts(pt0, v0)
        return self.minAngleToGridPts(pt0, pt1)

    # pt0 = (x0, y0)
    # pt1 = (x1, y1)
    def drawLinePts(self, pt0, pt1):
        cv.line(self._linesImg, pt0, pt1, (255,0,0), 2)

    # pt0 = (x0, y0)
    # v0 = (dx, dy)
    def drawLinePtAndVec(self, pt0, v0):
        (pt0, pt1) = self.ptAndVecToPts(pt0, v0)
        self.drawLinePts(pt0, pt1)

    # Line defined by all points for which
    # rho = x * cos(theta) + y * sin(theta)
    # see https://docs.opencv.org/3.0-beta/doc/py_tutorials/py_imgproc/py_houghlines/py_houghlines.html
    def drawLineParametric(self, rho, theta):
        a = np.cos(theta)
        b = np.sin(theta)
        self.drawLinePtAndVec((a*rho, b*rho), (-b, a))

class SplitSheets(ProcessingStep):
    numberOfSheets = 4

    def __init__(self,
                 name,
                 outputDir = 'data/tmp/',
                 sheet0 = (0, 0, .5, .5), # x0, y0, x1, y1 relative
                 sheet1 = (.5, 0, 1, .5), # x0, y0, x1, y1 relative
                 sheet2 = (0, .5, .5, 1), # x0, y0, x1, y1 relative
                 sheet3 = (.5, .5, 1, 1), # x0, y0, x1, y1 relative
                 threshold = 140,
                 kernelSize = 15,
                 log = helpers.Log(),
                 ):
        super().__init__(name, outputDir, log)
        self._sheets = [sheet0, sheet1, sheet2, sheet3]
        self._log = helpers.Log()
        self._threshold = threshold
        self._smallKernel = cv.getStructuringElement(cv.MORPH_RECT,
                (kernelSize, kernelSize))
        self._mediumKernel = cv.getStructuringElement(cv.MORPH_RECT,
                (kernelSize*4, kernelSize*2))

    def process(self, inputImg):
        super().process(inputImg)

        self._inputImg = inputImg
        self._outputImg = np.copy(inputImg)

        self._grayImgs = []
        self._thresholdImgs = []
        self._adaptiveThresholdImgs = []
        self._otsuThresholdImgs = []
        self._erodedImgs = []
        self._dilatedImgs = []
        self._labeledImgs = []
        self._foregroundImgs = []
        self._rotatedImgs = []
        self._outputSheetImgs = []
        for x0rel, y0rel, x1rel, y1rel in self._sheets:
            height, width, _ = self._inputImg.shape
            x0, y0 = int(x0rel*width), int(y0rel*height)
            x1, y1 = int(x1rel*width), int(y1rel*height)
            self.processSheet(np.copy(self._inputImg[y0:y1, x0:x1, :]))

    def processSheet(self, sheetImg):
        """
        Process one part of the input image, extracting only the white paper.

        return: True if a sheet image was extracted and stored in
        outputSheetImgs, else False.
        """
        sheetImgWidth, sheetImgHeight, _ = sheetImg.shape
        grayImg = cv.cvtColor(sheetImg, cv.COLOR_BGR2GRAY)
        otsuThresholdImg = cv.threshold(grayImg, self._threshold, 255,
                cv.THRESH_BINARY | cv.THRESH_OTSU)[1]
        adaptiveThresholdImg = cv.adaptiveThreshold(cv.medianBlur(grayImg,7), 255,
                cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY,11,2)
        testDilate = cv.dilate(adaptiveThresholdImg, cv.getStructuringElement(cv.MORPH_RECT,
                (7,7)), 1)
        adaptiveThresholdImg = np.where(
                cv.erode(testDilate, self._mediumKernel, 1) == 0,
                np.uint8(255.0), np.uint8(0.0))
        minAreaRect, adaptiveThresholdImg = self.biggestComponentMinAreaRect(adaptiveThresholdImg)
        cv.drawContours(adaptiveThresholdImg,[np.int0(cv.boxPoints(minAreaRect))],0,255,-1)
        thresholdImg = np.where(
                np.all([otsuThresholdImg == 255, adaptiveThresholdImg == 255], 0),
                np.uint8(255.0), np.uint8(0.0))

        erodedImg = cv.erode(thresholdImg, self._smallKernel, 1)
        dilatedImg = cv.dilate(erodedImg, self._mediumKernel, 1)
        foregroundSize = len(np.where(dilatedImg == 255)[0])
        self._log.debug(f'foregroundSize = {foregroundSize}')
        self._log.debug(f'imageSize = {sheetImgWidth * sheetImgHeight}')
        if foregroundSize < sheetImgWidth * sheetImgHeight / 4:
            self._log.info('found empty sheet')
            return False

        minAreaRect, foregroundImg = self.biggestComponentMinAreaRect(dilatedImg)
        foregroundImg = cv.cvtColor(grayImg, cv.COLOR_GRAY2BGR)
        cv.drawContours(foregroundImg,[np.int0(cv.boxPoints(minAreaRect))],0,(0,0,255),2)
        center, (minAreaRectWidth, minAreaRectHeight), rotationAngle = minAreaRect

        # extract the minAreaRect from sheetImg
        # cudos to http://felix.abecassis.me/2011/10/opencv-rotation-deskewing/
        if rotationAngle < -45.0:
            rotationAngle += 90.0
            minAreaRectWidth, minAreaRectHeight = minAreaRectHeight, minAreaRectWidth
        rotationMatrix = cv.getRotationMatrix2D(center, rotationAngle, 1.0)
        rotatedImg = cv.warpAffine(sheetImg, rotationMatrix, (sheetImgHeight, sheetImgWidth), flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)
        outputSheetImg = cv.getRectSubPix(rotatedImg, (int(minAreaRectWidth), int(minAreaRectHeight)), center)

        self._grayImgs.append(grayImg)
        self._adaptiveThresholdImgs.append(adaptiveThresholdImg)
        self._otsuThresholdImgs.append(otsuThresholdImg)
        self._thresholdImgs.append(thresholdImg)
        self._erodedImgs.append(erodedImg)
        self._dilatedImgs.append(dilatedImg)
        self._foregroundImgs.append(foregroundImg)
        self._rotatedImgs.append(rotatedImg)
        self._outputSheetImgs.append(outputSheetImg)

        return True

    def biggestComponentMinAreaRect(self, img):
        """
        Find the biggest white component in the img.
        Returns its minAreaRect and a black white image of the component.
        """
        numComponents, labeledImg = cv.connectedComponents(img)
        componentIndices = [np.where(labeledImg == label) for label in range(numComponents)]
        componentAreas = [len(idx[0]) for idx in componentIndices]
        componentColors = [np.median(img[idx]) for idx in componentIndices]

        # filter out black components, sort by size
        components = [(label, componentAreas[label], componentColors[label]) for label in
                range(numComponents) if componentColors[label] != 0]
        components.sort(key = lambda x: x[1], reverse=True)
        self._log.debug('components (label, size) = {}', list(components))

        selectedLabel = components[0][0]
        selectedImg = np.where(labeledImg == selectedLabel,
                np.uint8(255.0), np.uint8(0.0))
        contours, _ = cv.findContours(selectedImg, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        return cv.minAreaRect(contours[0]), selectedImg

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_0_0_input.jpg', self._inputImg)
        for idx, grayImg in enumerate(self._grayImgs):
            cv.imwrite(f'{self.prefix}_{idx}_1_grayImg.jpg', grayImg)
        for idx, thresholdImg in enumerate(self._adaptiveThresholdImgs):
            cv.imwrite(f'{self.prefix}_{idx}_2_adaptiveThresholdImg.jpg', thresholdImg)
        for idx, thresholdImg in enumerate(self._otsuThresholdImgs):
            cv.imwrite(f'{self.prefix}_{idx}_3_otsuThresholdImg.jpg', thresholdImg)
        for idx, thresholdImg in enumerate(self._thresholdImgs):
            cv.imwrite(f'{self.prefix}_{idx}_4_thresholdImg.jpg', thresholdImg)
        for idx, erodedImg in enumerate(self._erodedImgs):
            cv.imwrite(f'{self.prefix}_{idx}_5_erodedImg.jpg', erodedImg)
        for idx, dilatedImg in enumerate(self._dilatedImgs):
            cv.imwrite(f'{self.prefix}_{idx}_6_dilatedImg.jpg', dilatedImg)
        for idx, foregroundImg in enumerate(self._foregroundImgs):
            cv.imwrite(f'{self.prefix}_{idx}_7_foregroundImg.jpg', foregroundImg)
        for idx, rotatedImg in enumerate(self._rotatedImgs):
            cv.imwrite(f'{self.prefix}_{idx}_8_rotatedImg.jpg', rotatedImg)
        for idx, outputSheetImg in enumerate(self._outputSheetImgs):
            cv.imwrite(f'{self.prefix}_{idx}_9_outputSheetImg.jpg', outputSheetImg)

    def generatedSheets(self):
        return [f'{self.prefix}_{idx}_9_outputSheetImg.jpg'
                for idx, _ in enumerate(self._outputSheetImgs)]

class RotateSheet(LineBasedStep):
    def __init__(self,
                 name,
                 outputDir = 'data/tmp/',
                 log = helpers.Log(),
                 minLineLength = 200,
                 rotPrecision = np.pi/720,
                 maxLineGap = 5,
                 voteThreshold = 10,
                 kernelSize = 2):
        super().__init__(name, outputDir, log)
        self._minLineLength = minLineLength
        self._rotPrecision = rotPrecision
        self._maxLineGap = maxLineGap
        self._voteThreshold = voteThreshold
        self._kernelSize = kernelSize

    def process(self, inputImg):
        super().process(inputImg)

        self._inputImg = inputImg
        self._grayImg = cv.cvtColor(inputImg,cv.COLOR_BGR2GRAY)
        self._cannyImg = cv.Canny(self._grayImg,50,150,apertureSize = 3)
        kernel = cv.getStructuringElement(cv.MORPH_RECT, (self._kernelSize,
            self._kernelSize))
        self._closedImg = cv.morphologyEx(self._cannyImg, cv.MORPH_CLOSE, kernel)
        self._dilatedImg = cv.dilate(self._closedImg, kernel, 1)
        self._linesImg = np.copy(inputImg)

        lines = cv.HoughLinesP(self._dilatedImg, 1, self._rotPrecision, 1,
                minLineLength=self._minLineLength, maxLineGap=self._maxLineGap)

        if lines is None:
            rotationAngle = 0
        else:
            rotationAngle = self.computeRotationAngle(lines)

        fillColor = self.determineBackgroundFillColor()

        # align inputImg
        rows,cols,_ = inputImg.shape
        rotMatrix = cv.getRotationMatrix2D((cols/2, rows/2), rotationAngle, 1)
        self._outputImg = cv.warpAffine(inputImg, rotMatrix, (cols, rows),
                borderMode=cv.BORDER_REPLICATE)

    def computeRotationAngle(self, lines):
        """
        Compute a rotation angle which aligns the given lines to the x/y-axis
        as good as possible.
        """

        # for each line, vote for the smallest correction angle that would
        # make it align to the vertical or horizontal axis (discretized to a
        # certain number of buckets)
        numBuckets = int(2*np.pi/self._rotPrecision)
        buckets = np.zeros(numBuckets)
        for line in lines:
            x1,y1,x2,y2 = line[0]
            alpha = self.minAngleToGridPts((x1,y1),(x2,y2))
            bucketIdx = int(round(alpha / self._rotPrecision))
            buckets[bucketIdx] += 1
            self.drawLinePts((x1, y1), (x2, y2))
            cv.putText(self._linesImg, "{}".format(alpha*180/np.pi), (x1, y1),
                    cv.FONT_HERSHEY_SIMPLEX, 3, 5, cv.LINE_AA)

        # discard votes for buckets that didn't get enough votes
        buckets = [numVotes if numVotes>self._voteThreshold else 0 for numVotes in buckets]
        self._log.debug(["numVotes={}, angle={}".format(v, idx*self._rotPrecision*180/np.pi)
            for idx, v in enumerate(buckets) if v>0])

        # compute the weighted average of all correction angles still in the game
        # Caution! these are angles, so we average them on the unit circle
        angles = [idx*self._rotPrecision for idx, _ in enumerate(buckets)]
        if sum(buckets)==0:
            self._log.warn("""not enough votes for any correction angle found,
            omitting image rotation""")
            angle = 0
        else:
            weights = buckets / sum(buckets)
            xSum, ySum = 0, 0
            for angle, weight in zip(angles, weights):
                xSum += math.cos(angle)*weight
                ySum += math.sin(angle)*weight
            angle = math.atan(ySum/xSum)
            if xSum < 0: angle += np.pi
            if xSum > 0 and ySum < 0: angle += 2*np.pi
            self._log.debug(["angle={}, weight={}".format(a, w) for a, w in zip(angles, weights) if w > 0.0])
        correctionAngleDeg = angle * 180 / np.pi
        self._log.debug("correctionAngleDeg={}".format(correctionAngleDeg))
        return correctionAngleDeg

    def determineBackgroundFillColor(self):
        # determine average color of all pixels that are bright enough to be
        # considered background
        hsv = cv.cvtColor(self._inputImg, cv.COLOR_BGR2HSV)
        mask = cv.inRange(hsv, np.array((0, 0, 100)),
                np.array(np.array((180, 255, 255))))
        self._fillColorPixels = cv.bitwise_and(self._inputImg, self._inputImg, mask=mask)
        bValues = self._fillColorPixels[:,:,0]
        gValues = self._fillColorPixels[:,:,1]
        rValues = self._fillColorPixels[:,:,2]
        return (bValues.sum() / (bValues != 0).sum(),
                gValues.sum() / (gValues != 0).sum(),
                rValues.sum() / (rValues != 0).sum())

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_0_input.jpg', self._inputImg)
        cv.imwrite(f'{self.prefix}_1_gray.jpg', self._grayImg)
        cv.imwrite(f'{self.prefix}_2_canny.jpg', self._cannyImg)
        cv.imwrite(f'{self.prefix}_3_closed.jpg', self._closedImg)
        cv.imwrite(f'{self.prefix}_4_dilated.jpg', self._dilatedImg)
        cv.imwrite(f'{self.prefix}_5_houghlines.jpg', self._linesImg)
        cv.imwrite(f'{self.prefix}_7_fillColorPixels.jpg', self._fillColorPixels)
        cv.imwrite(f'{self.prefix}_8_output.jpg', self._outputImg)

class RotateLabel(ProcessingStep):
    def __init__(self,
                 name,
                 outputDir = 'data/tmp/',
                 log = helpers.Log(),
                 kernelSize = 12,
                 borderSize = 20):
        super().__init__(name, outputDir, log)
        self._kernelSize = kernelSize
        self._borderSize = borderSize

    def process(self, inputImg, originalImg):
        super().process(inputImg)
        self._inputImg = cv.copyMakeBorder(inputImg, self._borderSize,
                self._borderSize, self._borderSize, self._borderSize,
                cv.BORDER_CONSTANT, value=(0, 0, 0))
        self._originalImg = cv.copyMakeBorder(originalImg, self._borderSize,
                self._borderSize, self._borderSize, self._borderSize,
                cv.BORDER_CONSTANT, value=(0, 0, 0))

        closingKernel = cv.getStructuringElement(cv.MORPH_RECT,
                (int(self._kernelSize*1.5), self._kernelSize))
        self._closedImg = cv.morphologyEx(self._inputImg, cv.MORPH_CLOSE,
                closingKernel)
        dilationKernel = cv.getStructuringElement(cv.MORPH_RECT,
                (self._kernelSize*4, self._kernelSize))
        self._dilatedImg = cv.dilate(self._closedImg, dilationKernel, 1)

        # select 2nd biggest component, assumed to be the actual text
        numComponents, self._labeledImg, stats, _ = \
                cv.connectedComponentsWithStats(self._dilatedImg)
        labels = [label for label in range(numComponents)]
        labels.sort(key = lambda label: stats[label, cv.CC_STAT_AREA],
                reverse=True)
        textLabel = labels[1] if numComponents > 1 else labels[0]
        self._selectedImg = np.where(self._labeledImg == textLabel,
                np.uint8(255.0), np.uint8(0.0))

        # prepare labeled components for graphical output
        if numComponents > 1:
            self._labeledImg = self._labeledImg / (numComponents-1) * 255
        elif numComponents == 1:
            self._labeledImg = self._labeledImg * 255

        # find minAreaRect
        self._minAreaImg = np.copy(self._selectedImg)
        contours, _ = cv.findContours(self._selectedImg, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        minAreaRect = cv.minAreaRect(contours[0])
        center, (minAreaRectWidth, minAreaRectHeight), rotationAngle = minAreaRect
        self._minAreaImg = cv.cvtColor(self._minAreaImg, cv.COLOR_GRAY2BGR)
        cv.drawContours(self._minAreaImg,[np.int0(cv.boxPoints(minAreaRect))],0,(0,0,255),2)

        # extract the rotated minAreaRect from the original
        # cudos to http://felix.abecassis.me/2011/10/opencv-rotation-deskewing/
        if rotationAngle < -45.0:
            rotationAngle += 90.0
            minAreaRectWidth, minAreaRectHeight = minAreaRectHeight, minAreaRectWidth
        rotationMatrix = cv.getRotationMatrix2D(center, rotationAngle, 1.0)
        minAreaImgHeight, minAreaImgWidth, _ = self._minAreaImg.shape
        self._minAreaRotatedImg = cv.warpAffine(self._minAreaImg, rotationMatrix, (minAreaImgWidth, minAreaImgHeight), flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)
        originalImgHeight, originalImgWidth, _ = self._originalImg.shape
        rotatedImg = cv.warpAffine(self._originalImg, rotationMatrix, (originalImgWidth, originalImgHeight), flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)
        self._outputImg = cv.getRectSubPix(rotatedImg, (int(minAreaRectWidth), int(minAreaRectHeight)), center)

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_0_input.jpg', self._inputImg)
        cv.imwrite(f'{self.prefix}_1_closed.jpg', self._closedImg)
        cv.imwrite(f'{self.prefix}_2_dilated.jpg', self._dilatedImg)
        cv.imwrite(f'{self.prefix}_3_labeled.jpg', self._labeledImg)
        cv.imwrite(f'{self.prefix}_4_selected.jpg', self._selectedImg)
        cv.imwrite(f'{self.prefix}_5_minArea.jpg', self._minAreaImg)
        cv.imwrite(f'{self.prefix}_6_minAreaRotated.jpg', self._minAreaRotatedImg)
        cv.imwrite(f'{self.prefix}_7_output.jpg', self._outputImg)

class FindMarginsByLines(LineBasedStep):
    class Corner:
        def __init__(self, x, y):
            self.points = []
            self.addPoint(x, y)

        def addPoint(self, x, y):
            self.points.append((x, y))
            xSum, ySum = 0, 0
            for x0, y0 in self.points:
                xSum += x0
                ySum += y0
            self.x = int(round(xSum / len(self.points)))
            self.y = int(round(ySum / len(self.points)))

        def distanceToPoint(self, x, y):
            return math.sqrt(pow(x-self.x, 2) + pow(y-self.y, 2))

    threshold = 180
    def __init__(self,
                 name,
                 outputDir = 'data/tmp/',
                 log = helpers.Log(),
                 minLineLength = 800,
                 rotPrecision = np.pi/4,
                 maxLineGap = 1,
                 kernelSize = 9):
        super().__init__(name, outputDir, log)
        self._minLineLength = minLineLength
        self._rotPrecision = rotPrecision
        self._maxLineGap = maxLineGap
        self._cornerRadius = 6
        self._kernelSize = kernelSize

    def process(self, inputImg):
        super().process(inputImg)
        self._frameImg = np.copy(inputImg)
        self._grayImg = cv.cvtColor(inputImg,cv.COLOR_BGR2GRAY)
        self._cannyImg = cv.Canny(self._grayImg,50,150,apertureSize = 3)
        kernel = cv.getStructuringElement(cv.MORPH_RECT, (self._kernelSize,
            self._kernelSize))
        self._closedImg = self._cannyImg #cv.morphologyEx(self._cannyImg, cv.MORPH_CLOSE, kernel)
        self._closingImg = cv.dilate(self._closedImg, kernel, 1)
        _, self._thresholdImg = cv.threshold(self._grayImg, self.threshold, 1,
                cv.THRESH_BINARY_INV)

        self._linesImg = np.copy(inputImg)
        lines = cv.HoughLinesP(self._closingImg, 1, self._rotPrecision, 1,
                minLineLength=self._minLineLength, maxLineGap=self._maxLineGap)

        # map the end points of each line we found to a candidate corner
        corners = []
        def mapToCorner(x, y):
            foundCorner = False
            for c in corners:
                if c.distanceToPoint(x, y) < self._cornerRadius:
                    c.addPoint(x, y)
                    foundCorner = True
                    break
            if not foundCorner:
                corners.append(FindMarginsByLines.Corner(x, y))

        for line in lines:
            x1,y1,x2,y2 = line[0]
            mapToCorner(x1, y1)
            mapToCorner(x2, y2)
            self.drawLinePts((x1, y1), (x2, y2))

        # select the top left and bottom right corner - they probably span the
        # frame printed on each product sheet
        if len(corners) < 2:
            raise AssertionError('failed to find enough corner candidates')
        height, width, _ = self._linesImg.shape
        topLeft, topLeftDist = corners[0], width+height
        bottomRight, bottomRightDist = topLeft, topLeftDist
        for c in corners:
            cv.circle(self._linesImg, (c.x, c.y), self._cornerRadius, (0,255,0), 2)
            if c.distanceToPoint(0, 0) < topLeftDist:
                topLeft = c
                topLeftDist = c.distanceToPoint(0, 0)
            if c.distanceToPoint(width, height) < bottomRightDist:
                bottomRight = c
                bottomRightDist = c.distanceToPoint(width, height)

        # draw corners and selected rectangle, crop output image
        cv.circle(self._frameImg, (topLeft.x, topLeft.y), self._cornerRadius, (0,255,0), 2)
        cv.circle(self._frameImg, (bottomRight.x, bottomRight.y), self._cornerRadius, (0,255,0), 2)
        x0, y0 = topLeft.x, topLeft.y
        x1, y1 = bottomRight.x, bottomRight.y
        cv.rectangle(self._frameImg, (x0, y0), (x1, y1), (255,0,0), 9)
        self._outputImg=inputImg[y0:y1, x0:x1]

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_0_gray.jpg', self._grayImg)
        cv.imwrite(f'{self.prefix}_01_canny.jpg', self._cannyImg)
        cv.imwrite(f'{self.prefix}_02_closed.jpg', self._closedImg)
        cv.imwrite(f'{self.prefix}_03_closing.jpg', self._closingImg)
        cv.imwrite(f'{self.prefix}_1_threshold.jpg', self._thresholdImg*255)
        cv.imwrite(f'{self.prefix}_2_linesImg.jpg', self._linesImg)
        cv.imwrite(f'{self.prefix}_3_frames.jpg', self._frameImg)
        cv.imwrite(f'{self.prefix}_4_output.jpg', self._outputImg)

class FitToSheet(ProcessingStep):
    (frameP0, frameP1) = ProductSheet.getPageFramePts()

    def process(self, inputImg):
        super().process(inputImg)
        xMargin,yMargin = self.frameP0
        wMargin,hMargin = np.subtract(self.frameP1, self.frameP0)
        self._resizedImg = cv.resize(inputImg,(wMargin, hMargin))
        self._outputImg = cv.copyMakeBorder(self._resizedImg,yMargin,yMargin,xMargin,xMargin,cv.BORDER_CONSTANT,value=(255,255,255))

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_0_resizedImg.jpg', self._resizedImg)
        cv.imwrite(f'{self.prefix}_1_output.jpg', self._outputImg)

class RecognizeText(ProcessingStep):
    nextFallbackPageNumber = 0

    def __init__(self,
            name,
            outputDir,
            db,
            fallbackSheetName,
            marginSize = 5,
            minComponentArea = 100,
            minNormalizedAspectRatio = .1,
            confidenceThreshold = 0.5,
            log = helpers.Log()
            ):
        super().__init__(name, outputDir, log)
        self.__db = db
        self.__sheet = ProductSheet()
        self.__fallbackSheetName = fallbackSheetName
        self.__fallbackPageNumber = self.nextFallbackPageNumber
        RecognizeText.nextFallbackPageNumber += 1
        self.marginSize = marginSize
        self.confidenceThreshold = confidenceThreshold
        self.minComponentArea = minComponentArea
        self.minNormalizedAspectRatio = minNormalizedAspectRatio

    def productId(self):
        return self.__sheet.productId()

    def pageNumber(self):
        return self.__sheet.pageNumber

    def fileName(self):
        return self.__sheet.fileName()

    def process(self, inputImg):
        super().process(inputImg)
        self._inputImg = inputImg
        self._grayImg = cv.cvtColor(inputImg,cv.COLOR_BGR2GRAY)
        self._thresholdImg = 255-cv.adaptiveThreshold(self._grayImg, 255,
                cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY,11,3)
        closingKernel = cv.getStructuringElement(cv.MORPH_RECT, (5,5))
        self._closedImg = cv.morphologyEx(self._thresholdImg, cv.MORPH_CLOSE,
                closingKernel)
        openingKernel = cv.getStructuringElement(cv.MORPH_RECT, (4,4))
        self._openedImg = cv.morphologyEx(self._closedImg, cv.MORPH_OPEN,
                openingKernel)

        # prepare choices
        maxNumPages = self.__db.config.getint('tagtrail_gen',
                'max_num_pages_per_product')
        pageNumberString = self.__db.config.get('tagtrail_gen', 'page_number_string')
        pageNumbers = [pageNumberString.format(pageNumber=str(n)).upper()
                            for n in range(1, maxNumPages+1)]
        currency = self.__db.config.get('general', 'currency')
        names, units, prices = map(set, zip(*[
            (p.description.upper(),
             p.amountAndUnit.upper(),
             helpers.formatPrice(p.grossSalesPrice(), currency).upper())
            for p in self.__db.products.values()]))
        memberIds = [m.id for m in self.__db.members.values()]
        self._log.debug(f'names={list(names)}, units={list(units)}, prices={list(prices)}, ' +
                f'memberIds={list(memberIds)}, pageNumbers={list(pageNumbers)}')

        self._recognizedBoxTexts = {}
        for box in self.__sheet.boxes():
            if box.name == "nameBox":
                name, confidence = self.recognizeBoxText(box, names)
                if name == '' or confidence < 1:
                    box.text, box.confidence = self.__fallbackSheetName, 0
                else:
                    box.text, box.confidence = name, confidence
            elif box.name == "unitBox":
                box.text, box.confidence = self.recognizeBoxText(box, units)
                if box.text == '':
                    box.confidence = 0
            elif box.name == "priceBox":
                box.text, box.confidence = self.recognizeBoxText(box, prices)
                if box.text == '':
                    box.confidence = 0
            elif box.name == "pageNumberBox":
                pageNumber, confidence = self.recognizeBoxText(box,
                        pageNumbers)
                if pageNumber == '' or confidence < 1:
                    box.text, box.confidence = str(self.__fallbackPageNumber), 0
                else:
                    box.text, box.confidence = pageNumber, confidence
            elif box.name.find("dataBox") != -1:
                box.text, box.confidence = self.recognizeBoxText(box, memberIds)
            else:
                box.text, box.confidence = ("", 1.0)

        # try to fill in product infos if id is clear
        nameBox = self.__sheet.boxByName('nameBox')
        unitBox = self.__sheet.boxByName('unitBox')
        priceBox = self.__sheet.boxByName('priceBox')
        pageNumberBox = self.__sheet.boxByName('pageNumberBox')
        if nameBox.confidence == 1:
            product = self.__db.products[self.__sheet.productId()]
            expectedAmountAndUnit = product.amountAndUnit.upper()
            expectedPrice = helpers.formatPrice(product.grossSalesPrice(), currency).upper()
            if unitBox.confidence < 1:
                self._log.info(f'Inferred unit={expectedAmountAndUnit}')
                unitBox.text = expectedAmountAndUnit
                unitBox.confidence = 1
            elif unitBox.text != expectedAmountAndUnit:
                unitBox.confidence = 0
            if priceBox.confidence < 1:
                self._log.info(f'Inferred price={expectedPrice}')
                priceBox.text = expectedPrice
                priceBox.confidence = 1
            elif priceBox.text != expectedPrice:
                priceBox.confidence = 0
            if (product.previousQuantity < ProductSheet.maxQuantity()
                    and pageNumberBox.text == ''):
                # previousQuantity might also be small because many units were
                # already sold, while we still have more than one sheet
                # => this is just a good guess
                pageNumberBox.confidence = 0
                pageNumberBox.text = self.__db.config.get('tagtrail_gen',
                        'page_number_string').format(pageNumber='1')
                self._log.info(f'Inferred pageNumber={pageNumberBox.text}')

        # assume box should be filled if at least two neighbours are filled
        for box in self.__sheet.boxes():
            if box.text != '' or box.confidence == 0:
                continue
            numFilledNeighbours = 0
            for direction in ["Up", "Down", "Left", "Right"]:
                neighbourBox = self.__sheet.neighbourBox(box, direction)
                if neighbourBox is not None and neighbourBox.text != '':
                    numFilledNeighbours += 1
            if 2 <= numFilledNeighbours:
                box.confidence = 0

        for box in self.__sheet.boxes():
            if box.confidence < self.confidenceThreshold:
                box.bgColor = (0, 0, 80)

        self._outputImg = self.__sheet.createImg()

    """
    Returns (text, confidence) among candidateTexts
    """
    def recognizeBoxText(self, box, candidateTexts):
        (x0,y0),(x1,y1)=box.pt1,box.pt2
        openedImg = self._openedImg[y0-self.marginSize:y1+self.marginSize,
                x0-self.marginSize:x1+self.marginSize]
        originalImg = self._inputImg[y0-self.marginSize:y1+self.marginSize,
                x0-self.marginSize:x1+self.marginSize]
        cv.imwrite(f'{self.prefix}_0_{box.name}_0_originalImg.jpg', originalImg)
        cv.imwrite(f'{self.prefix}_0_{box.name}_1_openedImg.jpg', openedImg)

        numComponents, labeledImg, stats, _ = cv.connectedComponentsWithStats(openedImg)

        # find components touching the border of the image
        height, width = labeledImg.shape
        componentsTouchingBorder = set()
        for x in range(width):
            componentsTouchingBorder.add(labeledImg[0,x])
            componentsTouchingBorder.add(labeledImg[height-1,x])
        for y in range(height):
            componentsTouchingBorder.add(labeledImg[y,0])
            componentsTouchingBorder.add(labeledImg[y,width-1])
        self._log.debug(f'componentsTouchingBorder={list(componentsTouchingBorder)}')

        # remove spurious components
        bordersCleanedImg = labeledImg
        for label in range(numComponents):
            componentWidth = stats[label, cv.CC_STAT_WIDTH]
            componentHeight = stats[label, cv.CC_STAT_HEIGHT]
            normalizedAspectRatio = (min(componentWidth, componentHeight) /
                    max(componentWidth, componentHeight))
            self._log.debug(f'stats[label, cv.CC_STAT_WIDTH]={componentWidth}')
            self._log.debug(f'stats[label, cv.CC_STAT_HEIGHT]={componentHeight}')
            self._log.debug(f'normalizedAspectRatio={normalizedAspectRatio}')
            self._log.debug(f'stats[label, cv.CC_STAT_AREA]={stats[label, cv.CC_STAT_AREA]}')
            if (label in componentsTouchingBorder
                    or stats[label, cv.CC_STAT_AREA] < self.minComponentArea
                    or normalizedAspectRatio < self.minNormalizedAspectRatio):
                bordersCleanedImg = np.where(bordersCleanedImg == label,
                        np.uint8(0.0), bordersCleanedImg)

        bordersCleanedImg = np.where(bordersCleanedImg == 0,
                        np.uint8(0.0), np.uint8(255.0))
        labeledImg = labeledImg / numComponents * 255
        cv.imwrite(f'{self.prefix}_0_{box.name}_2_labeledImg.jpg', labeledImg)
        cv.imwrite(f'{self.prefix}_0_{box.name}_3_bordersCleanedImg.jpg', bordersCleanedImg)

        # assume empty box if not enough components are recognized
        numComponents, _ = cv.connectedComponents(bordersCleanedImg)
        self._log.debug(f'bordersCleanedImg of {box.name} has numComponents={numComponents}')
        if numComponents < 4:
            box.bgColor = (255, 0, 0)
            return ("", 1.0)

        p = RotateLabel(f'_0_{box.name}_3_rotation', self.prefix,
                log=self._log)
        p.process(bordersCleanedImg, originalImg)
        p.writeOutput()
        img = p._outputImg

        filename = f'{self.prefix}_0_{box.name}_4_ocrImage.jpg'
        cv.imwrite(filename, img)
        ocrText = pytesseract.image_to_string(PIL.Image.open(filename),
                config="--psm 7")

        confidence, text = self.findClosestString(ocrText.upper(), candidateTexts)
        self._log.info("(ocrText, confidence, text) = ({}, {}, {})", ocrText, confidence, text)
        return (text, confidence)

    def findClosestString(self, string, strings):
        strings=list(set(strings))
        self._log.debug("findClosestString: string={}, strings={}", string,
                strings)
        dists = list(map(lambda x: Levenshtein.distance(x, string), strings))
        self._log.debug("dists={}", dists)
        minDist, secondDist = np.partition(dists, 1)[:2]
        if minDist > 5 or minDist == secondDist:
            return 0, ""
        confidence = 1 - minDist / secondDist
        return confidence, strings[dists.index(minDist)]

    def resetSheetToFallback(self):
        self.__sheet.name = self.__fallbackSheetName
        self.__sheet.pageNumber = self.__fallbackPageNumber

    def storeSheet(self, outputDir):
        self.__sheet.store(outputDir)

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_1_grayImg.jpg', self._grayImg)
        cv.imwrite(f'{self.prefix}_2_thresholdImg.jpg', self._thresholdImg)
        cv.imwrite(f'{self.prefix}_3_closedImg.jpg', self._closedImg)
        cv.imwrite(f'{self.prefix}_4_openedImg.jpg', self._openedImg)
        cv.imwrite(f'{self.prefix}_5_output.jpg', self._outputImg)

def processFile(database, inputFile, outputDir, tmpDir):
    print('Processing file: ', inputFile)

    sheet0 = tuple(map(float,
        database.config.getcsvlist('tagtrail_ocr', 'sheet0_coordinates')))
    sheet1 = tuple(map(float,
        database.config.getcsvlist('tagtrail_ocr', 'sheet1_coordinates')))
    sheet2 = tuple(map(float,
        database.config.getcsvlist('tagtrail_ocr', 'sheet2_coordinates')))
    sheet3 = tuple(map(float,
        database.config.getcsvlist('tagtrail_ocr', 'sheet3_coordinates')))
    split = SplitSheets(
            "0_splitSheets",
            tmpDir,
            sheet0,
            sheet1,
            sheet2,
            sheet3)
    split.process(cv.imread(inputFile))
    split.writeOutput()
    for idx, sheetImg in enumerate(split._outputSheetImgs):
        sheetName = f'{os.path.split(inputFile)[1]}_sheet{idx}'
        print(f'sheetName = {sheetName}')
        sheetDir = f'{tmpDir}sheet_{idx}'
        helpers.recreateDir(sheetDir)
        processSheet(database, sheetImg, sheetName, outputDir, sheetDir+'/')
    return split.generatedSheets()

def processSheet(database, sheetImg, sheetName, outputDir, tmpDir):
    print('Processing sheet: ', sheetName)
    processors=[]
    processors.append(RotateSheet("1_rotateSheet", tmpDir))
    processors.append(FindMarginsByLines("2_findMarginsByLines", tmpDir))
    fit = FitToSheet("3_fitToSheet", tmpDir)
    processors.append(fit)
    recognizer = RecognizeText("4_recognizeText", tmpDir, database, sheetName)
    processors.append(recognizer)

    img = sheetImg
    for p in processors:
        p.process(img)
        p.writeOutput()
        img = p._outputImg
    if os.path.exists(f'{outputDir}{recognizer.fileName()}'):
        print(f'reset sheet to fallback, as {recognizer.fileName()} already exists')
        recognizer.resetSheetToFallback()

    recognizer.storeSheet(outputDir)
    cv.imwrite(f'{outputDir}{recognizer.productId()}_{recognizer.pageNumber()}_normalized_scan.jpg',
            fit._outputImg)

def main(accountingDir, tmpDir):
    outputDir = f'{accountingDir}2_taggedProductSheets/'
    helpers.recreateDir(outputDir)
    helpers.recreateDir(tmpDir)
    db = Database(f'{accountingDir}0_input/')
    partiallyFilledFiles = []
    for (parentDir, dirNames, fileNames) in walk('{}0_input/scans/'.format(accountingDir)):
        for f in fileNames:
            helpers.recreateDir(tmpDir+f)
            generatedSheets = processFile(db, parentDir + f, outputDir, tmpDir + f + '/')
            if len(generatedSheets) < SplitSheets.numberOfSheets:
                partiallyFilledFiles.append(f)

        print()
        print(f'processed {len(fileNames)} files')
        print(f'the following files generated less than {SplitSheets.numberOfSheets} sheets')
        for f in partiallyFilledFiles:
            print(parentDir + f)
        break

if __name__== "__main__":
    parser = argparse.ArgumentParser(
        description='Recognize tags on all input scans, storing them as CSV files')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    parser.add_argument('--tmpDir', dest='tmpDir', default='data/tmp/',
            help='Directory to put temporary files in')
    args = parser.parse_args()
    main(args.accountingDir, args.tmpDir)
