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
    # TODO: improve like that:
    # 1. cover background with black paper / color
    # 2. for each sheet, crop whole area, using relative coordinates to cope with
    # any resolution (as long as aspect ratio remains
    # 3. dilate generously, erode even a bit more, to get rid of text / lines
    # 4. take rotated min bounding box of biggest component as the sheet img
    def __init__(self,
                 name,
                 outputDir = 'data/tmp/',
                 log = helpers.Log(),
                 sheet0 = (220, 260, 1310, 1840), # x0, y0, x1, y1
                 sheet1 = (1700, 260, 2800, 1840), # x0, y0, x1, y1
                 sheet2 = (220, 2270, 1310, 3820), # x0, y0, x1, y1
                 sheet3 = (1700, 2270, 2800, 3820), # x0, y0, x1, y1
                 backgroundColorMin = (0, 00, 0), # hsv
                 backgroundColorMax = (180, 255, 150), # hsv
                 backgroundThreshold = 0.6):
        super().__init__(name, outputDir, log)
        self._sheets = [sheet0, sheet1, sheet2, sheet3]
        self._backgroundColorMin = backgroundColorMin
        self._backgroundColorMax = backgroundColorMax
        self._backgroundThreshold = backgroundThreshold

    def process(self, inputImg):
        super().process(inputImg)

        self._inputImg = inputImg
        self._outputImg = np.copy(inputImg)

        self._backgroundMasks = []
        self._outputSheetImgs = []
        for x0, y0, x1, y1 in self._sheets:
            sheetImg = np.copy(self._inputImg[y0:y1, x0:x1, :])
            hsv = cv.cvtColor(sheetImg, cv.COLOR_BGR2HSV)
            backgroundMask = cv.inRange(hsv, np.array(self._backgroundColorMin),
                    np.array(self._backgroundColorMax))
            self._backgroundMasks.append(backgroundMask)
            numBackgroundPixels = backgroundMask.sum().sum() / 255
            numPixelsTotal = (x1-x0) * (y1-y0)
            self._log.debug(f'backgroundPercentage = {numBackgroundPixels / numPixelsTotal}')
            if numBackgroundPixels / numPixelsTotal < self._backgroundThreshold:
                self._outputSheetImgs.append(sheetImg)
                self._outputImg[y0:y1, x0:x1, :] = 0

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_0_input.jpg', self._inputImg)
        for idx, backgroundMask in enumerate(self._backgroundMasks):
            cv.imwrite(f'{self.prefix}_0_{idx}_backgroundMask.jpg', backgroundMask)
        for idx, sheetImg in enumerate(self._outputSheetImgs):
            cv.imwrite(f'{self.prefix}_1_{idx}_sheetImg.jpg', sheetImg)
        cv.imwrite(f'{self.prefix}_{len(self._outputSheetImgs)}_outputImg.jpg', self._outputImg)

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

class RotateLabel(LineBasedStep):
    threshold = 127

    def __init__(self,
                 name,
                 outputDir = 'data/tmp/',
                 log = helpers.Log(),
                 kernelSize = 12):
        super().__init__(name, outputDir, log)
        self._kernelSize = kernelSize

    def process(self, inputImg):
        super().process(inputImg)
        self._inputImg = inputImg
        gray = cv.cvtColor(self._inputImg, cv.COLOR_BGR2GRAY)
        self._grayImg = cv.bitwise_not(gray)
        self._thresholdImg = cv.threshold(self._grayImg, self.threshold, 255, cv.THRESH_BINARY | cv.THRESH_OTSU)[1]

        kernel = cv.getStructuringElement(cv.MORPH_RECT,
                (int(self._kernelSize*1.5), self._kernelSize))
        self._closedImg = cv.morphologyEx(self._thresholdImg, cv.MORPH_CLOSE, kernel)
        self._dilatedImg = cv.dilate(self._closedImg, kernel, 1)
        numComponents, self._labeledImg = cv.connectedComponents(self._dilatedImg)
        # create tuples (label, size) for each connectedComponent
        components = list(map(lambda label:
                (label, len(np.where(self._labeledImg == label)[0])),
                range(numComponents)))
        components.sort(key = lambda x: x[1], reverse=True)
        self._log.debug('components (label, size) = {}', list(components))

        # assume the 2nd biggest component to be the actual text
        textLabel = components[1][0] if numComponents > 1 else components[0][0]
        self._selectedImg = np.where(self._labeledImg == textLabel , 255.0, 0.0)

        # prepare labeled components for graphical output
        if numComponents > 1:
            self._labeledImg = self._labeledImg / (numComponents-1) * 255
        elif numComponents == 1:
            self._labeledImg = self._labeledImg * 255

        self._selectedImg = cv.copyMakeBorder(
                self._selectedImg, 20, 20, 20, 20,
                cv.BORDER_CONSTANT, value=(0, 0, 0))
        self._selectedImg = cv.dilate(self._selectedImg, kernel, 1)

        self._linesImg = np.copy(self._selectedImg)
        coords = np.column_stack(np.where(self._selectedImg > 0.0))
        # fit line and compute rotation angle
        (vy, vx, y0, x0) = cv.fitLine(coords, cv.DIST_L2, 0, 0.01, 0.01)
        cv.circle(self._linesImg, (x0, y0), 10, (0,255,0), 2)
        cv.circle(self._linesImg, (x0+20*vx, y0+20*vy), 5, (255,0,0), 2)
        self.drawLinePtAndVec((x0, y0), (vx, vy))
        alpha=self.minAngleToGridPtAndVec((x0, y0), (vx, vy))
        self._log.debug("minAngleToGridPtAndVec = {:.2f}", alpha)
        angle=alpha * 180 / np.pi
        self._log.debug("rotation angle = {:.2f}", angle)

        # rotate line image for verification
        (h, w) = self._linesImg.shape[:2]
        center = (w // 2, h // 2)
        M = cv.getRotationMatrix2D(center, angle, 1.0)
        self._linesRotatedImg = cv.warpAffine(self._linesImg, M, (w, h),
                flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)

        # rotate inputImg
        (h, w) = self._inputImg.shape[:2]
        center = (w // 2, h // 2)
        M = cv.getRotationMatrix2D(center, angle, 1.0)
        self._outputImg = cv.warpAffine(self._inputImg, M, (w, h),
                flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_0_input.jpg', self._inputImg)
        cv.imwrite(f'{self.prefix}_1_gray.jpg', self._grayImg)
        cv.imwrite(f'{self.prefix}_2_threshold.jpg', self._thresholdImg)
        cv.imwrite(f'{self.prefix}_3_closed.jpg', self._closedImg)
        cv.imwrite(f'{self.prefix}_4_dilated.jpg', self._dilatedImg)
        cv.imwrite(f'{self.prefix}_5_labeled.jpg', self._labeledImg)
        cv.imwrite(f'{self.prefix}_6_selected.jpg', self._selectedImg)
        cv.imwrite(f'{self.prefix}_7_line.jpg', self._linesImg)
        cv.imwrite(f'{self.prefix}_8_lineRotated.jpg', self._linesRotatedImg)
        cv.imwrite(f'{self.prefix}_9a_input.jpg', self._inputImg)
        cv.imwrite(f'{self.prefix}_9b_output.jpg', self._outputImg)

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
    confidenceThreshold = 0.5
    nextFallbackPageNumber = 0

    def __init__(self,
            name,
            outputDir,
            db,
            fallbackSheetName,
            log = helpers.Log()
            ):
        super().__init__(name, outputDir, log)
        self.__db = db
        self.__sheet = ProductSheet()
        self.__fallbackSheetName = fallbackSheetName
        self.__fallbackPageNumber = self.nextFallbackPageNumber
        RecognizeText.nextFallbackPageNumber += 1

    def productId(self):
        return self.__sheet.productId()

    def pageNumber(self):
        return self.__sheet.pageNumber

    def process(self, inputImg):
        super().process(inputImg)
        self._inputImg = inputImg
        self._grayImg = cv.cvtColor(inputImg,cv.COLOR_BGR2GRAY)
        threshold = np.average(self._grayImg) * 0.8
        print(f'average = {np.average(self._grayImg)}')
        _, self._thresholdImg = cv.threshold(self._grayImg, threshold, 255,
                cv.THRESH_BINARY_INV)

        names, units, prices = zip(*[
            (p.description.upper(),
             str(p.amount).upper()+p.unit.upper(),
             helpers.formatPrice(p.grossSalesPrice()).upper())
            for p in self.__db.products.values()])
        memberIds = [m.id for m in self.__db.members.values()]
        self._log.debug("names={}, units={}, prices={}, memberIds={}", names,
                units, prices, memberIds)
        self._recognizedBoxTexts = {}
        for box in self.__sheet.boxes():
            if box.name == "nameBox":
                name, confidence = self.recognizeBoxText(box, names)
                if name == '' or confidence == 0:
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
                pageNumber, confidence = self.recognizeBoxText(box, map(str,
                    range(0,100)))
                if pageNumber == '' or confidence == 0:
                    box.text, box.confidence = str(self.__fallbackPageNumber), 0
                else:
                    box.text, box.confidence = pageNumber, confidence
            elif box.name.find("dataBox") != -1:
                box.text, box.confidence = self.recognizeBoxText(box, memberIds)
            else:
                box.text, box.confidence = ("", 1.0)

            if box.confidence < self.confidenceThreshold:
                box.bgColor = (0, 0, 80)

        self._outputImg = self.__sheet.createImg()

    """
    Returns (text, confidence) among candidateTexts
    """
    def recognizeBoxText(self, box, candidateTexts):
        (x0,y0),(x1,y1)=box.pt1,box.pt2
        m=20
        thresholdImg = self._thresholdImg[y0+m:y1-m,x0+m:x1-m]
        # assume empty box if not enough components are recognized
        numComponents, labeledImg = cv.connectedComponents(thresholdImg)
        labeledImg = labeledImg / numComponents * 255
        cv.imwrite(f'{self.prefix}_0_{box.name}_1_thresholdImg.jpg', thresholdImg)
        cv.imwrite(f'{self.prefix}_0_{box.name}_2_labeledImg.jpg', labeledImg)
        self._log.debug(f'{box.name} has numComponents={numComponents}')
        if numComponents < 4:
            box.bgColor = (255, 0, 0)
            return ("", 1.0)

        kernel = cv.getStructuringElement(cv.MORPH_RECT, (2,2))
        inputImg = cv.erode(self._inputImg[y0+m:y1-m,x0+m:x1-m], kernel, 1)
        p = RotateLabel(f'_0_{box.name}_3_rotation', self.prefix, log=self._log)
        p.process(inputImg)
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

    def storeSheet(self, outputDir):
        self.__sheet.store(outputDir)

    def writeOutput(self):
        cv.imwrite(f'{self.prefix}_1_grayImg.jpg', self._grayImg)
        cv.imwrite(f'{self.prefix}_2_thresholdImg.jpg', self._thresholdImg)
        cv.imwrite(f'{self.prefix}_3_output.jpg', self._outputImg)

def processFile(database, inputFile, outputDir, tmpDir):
    print('Processing file: ', inputFile)
    split = SplitSheets("0_splitSheets", tmpDir)
    split.process(cv.imread(inputFile))
    split.writeOutput()
    for idx, sheetImg in enumerate(split._outputSheetImgs):
        sheetName = f'{os.path.split(inputFile)[1]}_sheet{idx}'
        print(f'sheetName = {sheetName}')
        sheetDir = f'{tmpDir}sheet_{idx}'
        helpers.recreateDir(sheetDir)
        processSheet(database, sheetImg, sheetName, outputDir, sheetDir+'/')

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
    recognizer.storeSheet(outputDir)
    cv.imwrite(f'{outputDir}{recognizer.productId()}_{recognizer.pageNumber()}_normalized_scan.jpg',
            fit._outputImg)

def main(accountingDir, tmpDir):
    outputDir = f'{accountingDir}2_taggedProductSheets/'
    helpers.recreateDir(outputDir)
    helpers.recreateDir(tmpDir)
    db = Database(f'{accountingDir}0_input/')
    for (parentDir, dirNames, fileNames) in walk('{}0_input/scans/'.format(accountingDir)):
        for f in fileNames:
            helpers.recreateDir(tmpDir+f)
            processFile(db, parentDir + f, outputDir, tmpDir + f + '/')
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
