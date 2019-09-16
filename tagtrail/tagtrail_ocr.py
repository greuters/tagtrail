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

import cv2 as cv
import numpy as np
import itertools
import pytesseract
import PIL
import os
import math
import Levenshtein
from abc import ABC, abstractmethod
from helpers import Log
from sheets import ProductSheet
from database import Database
from os import walk

class ProcessingStep(ABC):
    def __init__(self,
            name,
            outputPath = 'data/tmp',
            log = Log()):
        self._name = name
        self._log = log
        self._outputPath = outputPath
        super().__init__()

    @abstractmethod
    def process(self, inputImg):
        self._log.info("#ProcessStep: {}".format(self._name))
        self._outputImg = inputImg

    def writeOutput(self):
        cv.imwrite("{}/{}.jpg".format(self._outputPath, self._name), self._outputImg)

class RotationStep(ProcessingStep):
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

class RotateSheet(RotationStep):
    def __init__(self,
                 name,
                 outputPath = 'data/tmp',
                 log = Log(),
                 minLineLength = 200,
                 rotPrecision = np.pi/720,
                 maxLineGap = 5,
                 voteThreshold = 10,
                 kernelSize = 2):
        super().__init__(name, outputPath, log)
        self._minLineLength = minLineLength
        self._rotPrecision = rotPrecision
        self._maxLineGap = maxLineGap
        self._voteThreshold = voteThreshold
        self._kernelSize = kernelSize

    def process(self, inputImg):
        super().process(inputImg)
        # 1. find all lines in the image, using some filters to improve results
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

        # 2. for each line, vote for the smallest correction angle that would
        #    make it align to the vertical or horizontal axis (discretized to a
        #    certain number of buckets)
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

        # 3. discard votes for buckets that didn't get enough
        buckets = [numVotes if numVotes>self._voteThreshold else 0 for numVotes in buckets]
        self._log.debug(["numVotes={}, angle={}".format(v, idx*self._rotPrecision*180/np.pi)
            for idx, v in enumerate(buckets) if v>0])

        # 4. compute the weighted average of all correction angles still in the game
        #    Caution! these are angles, so we average them on the unit circle
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

        # 5. align inputImg
        rows,cols,_ = inputImg.shape
        rotMatrix = cv.getRotationMatrix2D((cols/2, rows/2), correctionAngleDeg, 1)
        self._outputImg = cv.warpAffine(inputImg, rotMatrix, (cols, rows), borderMode=cv.BORDER_CONSTANT,
                borderValue=(255, 255, 255))

    def writeOutput(self):
        cv.imwrite("{}/{}_0_input.jpg".format(self._outputPath, self._name), self._inputImg)
        cv.imwrite("{}/{}_1_gray.jpg".format(self._outputPath, self._name), self._grayImg)
        cv.imwrite("{}/{}_2_canny.jpg".format(self._outputPath, self._name), self._cannyImg)
        cv.imwrite("{}/{}_3_closed.jpg".format(self._outputPath, self._name), self._closedImg)
        cv.imwrite("{}/{}_4_dilated.jpg".format(self._outputPath, self._name), self._dilatedImg)
        cv.imwrite("{}/{}_5_houghlines.jpg".format(self._outputPath, self._name), self._linesImg)
        cv.imwrite("{}/{}_6_output.jpg".format(self._outputPath, self._name), self._outputImg)

class RotateLabel(RotationStep):
    threshold = 127

    def __init__(self,
                 name,
                 outputPath = 'data/tmp',
                 log = Log(),
                 kernelSize = 10):
        super().__init__(name, outputPath, log)
        self._kernelSize = kernelSize

    def process(self, inputImg):
        super().process(inputImg)
        self._inputImg = inputImg
        self._linesImg = np.copy(inputImg)
        gray = cv.cvtColor(self._inputImg, cv.COLOR_BGR2GRAY)
        self._grayImg = cv.bitwise_not(gray)
        self._thresholdImg = cv.threshold(self._grayImg, self.threshold, 255, cv.THRESH_BINARY | cv.THRESH_OTSU)[1]

        kernel = cv.getStructuringElement(cv.MORPH_RECT, (self._kernelSize,
            self._kernelSize))
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
        self._selectedImg = np.where(self._labeledImg ==
                components[1][0], 255, 0)

        # prepare labeled components for graphical output
        if numComponents > 1:
            self._labeledImg = self._labeledImg / (numComponents-1) * 255
        elif numComponents == 1:
            self._labeledImg = self._labeledImg * 255

        self._selectedImg = cv.copyMakeBorder(
                self._selectedImg, 20, 20, 20, 20,
                cv.BORDER_CONSTANT, value=(0, 0, 0))
        coords = np.column_stack(np.where(self._selectedImg > 0))
        # fit line and compute rotation angle
        #coords = np.column_stack(np.where(self._thresholdImg > 0))
        #(vx, vy, x0, y0) = cv.fitLine(coords, cv.DIST_L2, 0, 0.01, 0.01)
        #self.drawLinePtAndVec((x0, y0), (vx, -vy))
        #alpha=self.minAngleToGridPtAndVec((x0, y0), (vx, -vy))
        #print(alpha)
        #angle=alpha * 180 / np.pi
        #self._log.info("rotation angle = {:.2f}", angle)

        # fit minimal bounding rectangle
        angle = cv.minAreaRect(coords)[-1]
        if angle < -45:
                angle = -(90 + angle)
        else:
                angle = -angle
        self._log.info("rotation angle = {:.2f}", angle)

        # rotate
        (h, w) = self._inputImg.shape[:2]
        center = (w // 2, h // 2)
        M = cv.getRotationMatrix2D(center, angle, 1.0)
        self._outputImg = cv.warpAffine(self._inputImg, M, (w, h),
                flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)

    def writeOutput(self):
        cv.imwrite("{}/{}_0_input.jpg".format(self._outputPath, self._name),
                self._inputImg)
        cv.imwrite("{}/{}_1_gray.jpg".format(self._outputPath, self._name),
                self._grayImg)
        cv.imwrite("{}/{}_2_threshold.jpg".format(self._outputPath,
            self._name), self._thresholdImg)
        cv.imwrite("{}/{}_3_closed.jpg".format(self._outputPath,
            self._name), self._closedImg)
        cv.imwrite("{}/{}_4_dilated.jpg".format(self._outputPath,
            self._name), self._dilatedImg)
        cv.imwrite("{}/{}_5_labeled.jpg".format(self._outputPath,
            self._name), self._labeledImg)
        cv.imwrite("{}/{}_6_selected.jpg".format(self._outputPath,
            self._name), self._selectedImg)
        cv.imwrite("{}/{}_7_line.jpg".format(self._outputPath, self._name),
                self._linesImg)
        cv.imwrite("{}/{}_8_output.jpg".format(self._outputPath, self._name),
                self._outputImg)

# identify main Sheet area
class FindMargins(ProcessingStep):
    threshold = 240
    precisionWeight = 0.5

    @abstractmethod
    def process(self, inputImg):
        super().process(inputImg)
        self._x0, self._y0 = 0, 0
        self._x1, self._y1, _ = inputImg.shape
        self._marginImg = np.copy(inputImg)
        self._grayImg = cv.cvtColor(inputImg, cv.COLOR_BGR2GRAY)
        _, self._thresholdImg = cv.threshold(self._grayImg, self.threshold, 1,
                cv.THRESH_BINARY)
        self._blackCountTotal, _ = np.bincount(self._thresholdImg.flatten(), minlength=2)

    def writeOutput(self):
        cv.imwrite("{}/{}_0_gray.jpg".format(self._outputPath, self._name), self._grayImg*255)
        cv.imwrite("{}/{}_1_threshold.jpg".format(self._outputPath, self._name), self._thresholdImg*255)
        cv.imwrite("{}/{}_2_margins.jpg".format(self._outputPath, self._name), self._marginImg)
        cv.imwrite("{}/{}_3_output.jpg".format(self._outputPath, self._name), self._outputImg)

    def updateRect(self,x0,y0,x1,y1,drawRect=False):
        # positives = blackPixels
        blackCount, _ = np.bincount(self._thresholdImg[y0:y1,x0:x1].flatten(), minlength=2)
        self._log.debug("x0={}, y0={}, x1={}, y1={}".format(x0, y0, x1, y1))
        self._log.debug(blackCount)
        self._log.debug(self._thresholdImg[y0:y1,x0:x1].flatten())
        if blackCount == 0:
            self._log.debug("score=0")
            return 0
        precision=blackCount / ((x1-x0)*(y1-y0))
        recall=blackCount / self._blackCountTotal
        betaSquared = self.precisionWeight * self.precisionWeight
        score=(1+betaSquared)*(precision*recall)/(betaSquared*precision + recall)
        #score=2*(precision*recall)/(precision + recall)
        self._log.debug("precision={}, recall={}, score={}".format(precision, recall, score))
        if drawRect:
            cv.rectangle(self._marginImg,(x0,y0),(x1,y1),(0,255,255),5)

        if score>self._maxScore:
            self._log.info("new maxScore={}".format(score))
            self._log.info("bestRect (x0, y0), (x1, y1) = ({}, {}), ({}, {})",
                    x0, y0, x1, y1)
            self._maxScore = score
            self._x0,self._y0,self._x1,self._y1 = x0,y0,x1,y1

class FindMarginsByContour(FindMargins):
    localOptimizationRange = 15

    def process(self, inputImg):
        super().process(inputImg)
        kernel = cv.getStructuringElement(cv.MORPH_RECT, (15,15))
        self._closingImg = cv.morphologyEx(self._thresholdImg, cv.MORPH_CLOSE, kernel)
        self._blackCountTotal, _ = np.bincount(self._closingImg.flatten(), minlength=2)
        contours, _ = cv.findContours(self._closingImg, cv.RETR_TREE, cv.CHAIN_APPROX_SIMPLE)

        # first pass - find the best contour
        self._maxScore = 0
        for cnt in contours:
            x,y,w,h=cv.boundingRect(cnt)
            self.updateRect(x, y, x+w, y+h, True)
        cv.rectangle(self._marginImg,(self._x0,self._y0),(self._x1,self._y1),(0,0,255),9)

        # second pass - try to find an optimum locally
        # optimizing one variable at a time for performance reasons
        optimizationRange = [x for x in range(-self.localOptimizationRange, self.localOptimizationRange) if x != 0]
        for dx in optimizationRange:
            self.updateRect(self._x0+dx,self._y0,self._x1,self._y1, True)
        for dy in optimizationRange:
            self.updateRect(self._x0,self._y0+dy,self._x1,self._y1, True)
        for dx in optimizationRange:
            self.updateRect(self._x0,self._y0,self._x1+dx,self._y1, True)
        for dy in optimizationRange:
            self.updateRect(self._x0,self._y0,self._x1,self._y1+dy, True)
        cv.rectangle(self._marginImg,(self._x0,self._y0),(self._x1,self._y1),(255,0,0),9)

        self._outputImg=inputImg[self._y0:self._y1,self._x0:self._x1]

    def writeOutput(self):
        super().writeOutput()
        cv.imwrite("{}/{}_1a_closing.jpg".format(self._outputPath, self._name), self._closingImg*255)

class FitToSheet(ProcessingStep):
    (marginP0, marginP1) = ProductSheet.getPageMarginPts()

    def process(self, inputImg):
        super().process(inputImg)
        xMargin,yMargin = self.marginP0
        wMargin,hMargin = np.subtract(self.marginP1, self.marginP0)
        self._resizedImg = cv.resize(inputImg,(wMargin, hMargin))
        self._outputImg = cv.copyMakeBorder(self._resizedImg,yMargin,yMargin,xMargin,xMargin,cv.BORDER_CONSTANT,value=(255,255,255))

    def writeOutput(self):
        cv.imwrite("{}/{}_0_resizedImg.jpg".format(self._outputPath, self._name), self._resizedImg)
        cv.imwrite("{}/{}_1_output.jpg".format(self._outputPath, self._name), self._outputImg)

class RecognizeText(ProcessingStep):
    threshold = 127
    confidenceThreshold = 0.5
    def __init__(self,
            name):
        super().__init__(name)
        dataFilePath = 'data/database/{}'
        db = Database(dataFilePath.format('mitglieder.csv'),
                dataFilePath.format('produkte.csv'))
        self._sheet = ProductSheet("not", "known", "yet",
                ProductSheet.maxQuantity(),
                db)

    def process(self, inputImg):
        super().process(inputImg)
        self._inputImg = inputImg
        self._grayImg = cv.cvtColor(inputImg,cv.COLOR_BGR2GRAY)
        _, self._thresholdImg = cv.threshold(self._grayImg, self.threshold, 255,
                cv.THRESH_BINARY)

        names, units, prices =zip(*[(p._description.upper(), p._unit.upper(), p._price.upper()) for p
            in self._sheet._database._products.values()])
        memberIds = [m._id for m in self._sheet._database._members.values()]
        self._log.debug("names={}, units={}, prices={}, memberIds={}", names,
                units, prices, memberIds)
        self._recognizedBoxTexts = {}
        for box in self._sheet._boxes:
            if box.name == "nameBox":
                box.text, box.confidence = self.recognizeBoxText(box, names)
                self._sheet.name = box.text
            elif box.name == "unitBox":
                box.text, box.confidence = self.recognizeBoxText(box, units)
                self._sheet.unit = box.text
            elif box.name == "priceBox":
                box.text, box.confidence = self.recognizeBoxText(box, prices)
                self._sheet.price = box.text
            elif box.name.find("dataBox") != -1:
                box.text, box.confidence = self.recognizeBoxText(box, memberIds)
            else:
                box.text, box.confidence = ("", 1.0)

            if box.confidence < self.confidenceThreshold:
                box.bgColor = (0, 0, 80)

        self._outputImg = self._sheet.createImg()

    """
    Returns (text, confidence) among candidateTexts
    """
    def recognizeBoxText(self, box, candidateTexts):
        (x0,y0),(x1,y1)=box.pt1,box.pt2
        m=20
        thresholdImg = self._thresholdImg[y0+m:y1-m,x0+m:x1-m]
        if np.min(thresholdImg) == 255 or np.max(thresholdImg) == 0:
            return ("", 1.0)

        kernel = cv.getStructuringElement(cv.MORPH_RECT, (2,2))
        inputImg = cv.erode(self._inputImg[y0+m:y1-m,x0+m:x1-m], kernel, 1)
        p = RotateLabel("{}_{}_rotation".format(self._name, box.name), log=self._log)
        p.process(inputImg)
        p.writeOutput()
        img = p._outputImg

        filename = "{}/label_{}.jpg".format(self._outputPath, box.name)
        cv.imwrite(filename, img)
        ocrText = pytesseract.image_to_string(PIL.Image.open(filename),
                config="--psm 7")
        #os.remove(filename)

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

    def writeOutput(self):
        cv.imwrite("{}/{}_0_grayImg.jpg".format(self._outputPath, self._name), self._grayImg)
        cv.imwrite("{}/{}_1_output.jpg".format(self._outputPath, self._name), self._outputImg)

def processFile(inputFile, outputDir):
    print('Processing file: ', inputFile)
    processors=[]
    processors.append(RotateSheet("0_rotateSheet"))
    processors.append(FindMarginsByContour("1_findMargins"))
    fit = FitToSheet("2_fitToSheet")
    processors.append(fit)
    recognizer = RecognizeText("3_recognizeText")
    processors.append(recognizer)
    img = cv.imread(inputFile)
    for p in processors:
        p.process(img)
        p.writeOutput()
        img = p._outputImg
    recognizer._sheet.store(outputDir)
    cv.imwrite("{}{}_normalized_scan.jpg".format(outputDir,
        recognizer._sheet.name), fit._outputImg)



def main():
    outputDir = 'data/ocr_out/'
    inputDir = 'data/scans/'
    for (dirPath, dirNames, fileNames) in walk(inputDir):
        for f in fileNames:
            processFile(dirPath + f, outputDir)
        break

if __name__== "__main__":
    main()
