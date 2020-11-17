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
from tesserocr import PyTessBaseAPI, PSM
import PIL
import os
import math
import Levenshtein
import slugify
import tkinter
from tkinter import ttk
from tkinter import messagebox
from tkinter.simpledialog import Dialog
import imutils
import functools
from PIL import ImageTk,Image
from abc import ABC, abstractmethod

from . import helpers
from .sheets import ProductSheet
from .database import Database
from .gui_components import BaseGUI

class ScanSplitter():
    numberOfSheets = 4
    normalizedWidth = 3672
    normalizedHeight = 6528
    minSheetSize = 1000*1500

    """
    A processor that takes scanned/captured images with up to four sheets on it
    as input, splits them into four regions and decides whether each region
    contains a sheet or is empty.

    :param name: name of the processor, used to identify logs and debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    :param sheetRegion0: relative coordinates of top left sheet, (topLeftX, topLeftY,
        bottomRightX, bottomRightY)
    :type sheetRegion0: tuple of float, each between 0.0 and 1.0
    :param sheetRegion1: relative coordinates of top left sheet, (topLeftX, topLeftY,
        bottomRightX, bottomRightY)
    :type sheetRegion1: tuple of float, each between 0.0 and 1.0
    :param sheetRegion2: relative coordinates of top left sheet, (topLeftX, topLeftY,
        bottomRightX, bottomRightY)
    :type sheetRegion2: tuple of float, each between 0.0 and 1.0
    :param sheetRegion3: relative coordinates of top left sheet, (topLeftX, topLeftY,
        bottomRightX, bottomRightY)
    :type sheetRegion3: tuple of float, each between 0.0 and 1.0
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False,
                 log = helpers.Log(),
                 sheetRegion0 = (0, 0, .5, .5),
                 sheetRegion1 = (.5, 0, 1, .5),
                 sheetRegion2 = (0, .5, .5, 1),
                 sheetRegion3 = (.5, .5, 1, 1),
                 ):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.log = log
        self.__sheetRegions = [sheetRegion0, sheetRegion1, sheetRegion2, sheetRegion3]

    def process(self, inputImg):
        """
        Process a scanned image

        For each processed scan

        - four images are appended to self.unprocessedSheetImgs
          (cropped sheet regions without further processing)
        - for each of the four possible sheets, a normalized image of the
          actual sheet or None is appended to self.outputSheetImgs

        :param inputImg: scanned image with up to four ProductSheets printed on
        :type inputImg: BGR image
        """
        self.__inputImg = cv.resize(inputImg, (self.normalizedWidth,
            self.normalizedHeight), Image.BILINEAR)

        self.__grayImgs = []
        self.__blurredImgs = []
        self.__otsuThresholdImgs = []
        self.__sheetImgs = []
        self.unprocessedSheetImgs = []
        self.outputSheetImgs = []
        for idx, (x0rel, y0rel, x1rel, y1rel) in enumerate(self.__sheetRegions):
            height, width, _ = self.__inputImg.shape
            x0, y0 = int(x0rel*width), int(y0rel*height)
            x1, y1 = int(x1rel*width), int(y1rel*height)
            unprocessedSheetImg = np.copy(self.__inputImg[y0:y1, x0:x1, :])
            self.unprocessedSheetImgs.append(unprocessedSheetImg)
            self.outputSheetImgs.append(self.__processSheet(unprocessedSheetImg,
                idx))

        if self.writeDebugImages:
            self.__writeDebugImages()

    def __processSheet(self, sheetImg, sheetRegionIdx):
        """
        Identify if a sheet exists in an image and crop it to contain only the
        sheet

        :param sheetImg: image of a region of the scan that could contain a
            single sheet
        :type sheetImg: BGR image
        :param sheetRegionIdx; idx of the region, used to name debug images
        :type sheetRegionIdx: str
        :return: corpped image of the sheet or None
        :rtype: BGR image
        """
        gray = cv.cvtColor(sheetImg, cv.COLOR_BGR2GRAY)
        blurred = cv.GaussianBlur(gray, (7, 7), 3)
        _, otsu = cv.threshold(blurred, 0, 255, cv.THRESH_BINARY+cv.THRESH_OTSU)

        self.__grayImgs.append(gray)
        self.__blurredImgs.append(blurred)
        self.__otsuThresholdImgs.append(otsu)

        # find biggest contour in the thresholded image
        cnts = cv.findContours(otsu, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
        cnts = imutils.grab_contours(cnts)
        cnts = sorted(cnts, key=cv.contourArea, reverse=True)

        if cnts == []:
            self.log.debug(f'assume empty sheet (no sheet contour found)')
            return None

        # biggest contour is assumed to be the sheet
        sheetContour = cnts[0]
        cntX, cntY, cntW, cntH = cv.boundingRect(sheetContour)

        if cntW * cntH < self.minSheetSize:
            self.log.debug(f'assume empty sheet (sheet contour too small)')
            return None

        sheet = np.copy(sheetImg[cntY:cntY+cntH, cntX:cntX+cntW])
        self.__sheetImgs.append(sheet)

        frameFinder = ContourBasedFrameFinder(f'{self.name}_sheet{sheetRegionIdx}_5_frameFinder',
                self.tmpDir, self.writeDebugImages, self.log)
        frameContour = frameFinder.process(sheet)
        if frameContour is None:
            findMarginsByLines = LineBasedFrameFinder(
                    f'{self.name}_sheet{sheetRegionIdx}_6_frameFinderByLines',
                    self.tmpDir, self.writeDebugImages, self.log)
            frameContour = findMarginsByLines.process(sheet)

        if frameContour is None:
            self.log.debug(f'assume empty sheet (no frame contour found)')
            return None

        normalizer = SheetNormalizer(
                f'{self.name}_sheet{sheetRegionIdx}_7_normalizer',
                self.tmpDir, self.writeDebugImages, self.log)
        return normalizer.process(sheet, frameContour)

    def __writeDebugImages(self):
        """
        Write debug images to tmpDir
        """
        def writeImg(img, sheetRegionIdx, imgName):
            if img is not None:
                cv.imwrite(f'{self.tmpDir}{self.name}_sheet{sheetRegionIdx}_{imgName}.jpg', img)

        writeImg(self.__inputImg, 0, '0_input.jpg')
        for idx, img in enumerate(self.__grayImgs):
            writeImg(img, idx, '1_grayImg.jpg')
        for idx, img in enumerate(self.__blurredImgs):
            writeImg(img, idx, '2_blurredImg.jpg')
        for idx, img in enumerate(self.__otsuThresholdImgs):
            writeImg(img, idx, '3_otsuThresholdImg.jpg')
        for idx, img in enumerate(self.__sheetImgs):
            writeImg(img, idx, '4_sheetImg.jpg')
        for idx, img in enumerate(self.outputSheetImgs):
            writeImg(img, idx, '8_outputSheetImg.jpg')

class ContourBasedFrameFinder():
    """
    A processor that takes an image which presumably contains a ProductSheet
    printed on white paper as input and identifies the contour of the bold
    frame on it.

    :class:`ContourBasedFrameFinder` is precise (almost no wrong contours detected) and
    faster than :class:`LineBasedFrameFinder`, but often misses distorted frames (e.g.
    if a corner is folded or a tag placed over the frame)

    :param name: name of the processor, used to identify logs and debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False,
                 log = helpers.Log(),
                 ):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.log = log

    @property
    def __prefix(self):
        """
        Prefix string to prepend before debug image names
        """
        return f'{self.tmpDir}{self.name}'

    def process(self, inputImg):
        """
        Identify the frame of a ProductSheet

        :param inputImg: image of a product sheet
        :type inputImg: BGR image
        :return: approximate contour of the frame with four corners, or None if
            no sensible contour could be found
        :rtype: list of four points ([int, int] each) or None
        """

        grayImg = cv.cvtColor(inputImg, cv.COLOR_BGR2GRAY)
        blurredImg = cv.GaussianBlur(grayImg, (7, 7), 3)
        thresholdImg = cv.adaptiveThreshold(blurredImg, 255,
                cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY, 11, 2)
        thresholdImg = cv.bitwise_not(thresholdImg)

        # find sheet frame, assuming it is the biggest contour on the image
        # which can be approximated with four points
        cnts = cv.findContours(thresholdImg, cv.RETR_LIST,
                cv.CHAIN_APPROX_SIMPLE)
        cnts = imutils.grab_contours(cnts)
        cnts = sorted(cnts, key=cv.contourArea, reverse=True)

        approxFrameContour = None
        frameContour = None
        for c in cnts:
            peri = cv.arcLength(c, True)
            approx = cv.approxPolyDP(c, 0.003 * peri, True)
            if len(approx) == 4:
                approxFrameContour = approx
                frameContour = c
                break

        if self.writeDebugImages:
            contourImg = inputImg.copy()
            frameContourSeen = False
            for c in cnts:
                if np.array_equal(c, frameContour):
                    frameContourSeen = True
                    cv.drawContours(contourImg, [c], -1, (0, 255, 0), 4)
                elif frameContourSeen:
                    cv.drawContours(contourImg, [c], -1, (255, 0, 0), 1)
                else:
                    cv.drawContours(contourImg, [c], -1, (0, 0, 255), 2)
            cv.imwrite(f'{self.__prefix}_0_input.jpg', inputImg)
            cv.imwrite(f'{self.__prefix}_1_gray.jpg', grayImg)
            cv.imwrite(f'{self.__prefix}_2_blurred.jpg', blurredImg)
            cv.imwrite(f'{self.__prefix}_3_threshold.jpg', thresholdImg)
            cv.imwrite(f'{self.__prefix}_4_contours.jpg', contourImg)

        if approxFrameContour is None:
            self.log.debug(f'no frame contour found')
            return None

        imgH, imgW = thresholdImg.shape
        _, _, cntW, cntH = cv.boundingRect(approxFrameContour)
        fillRatio = (cntW * cntH) / (imgW * imgH)
        if fillRatio < .25:
            self.log.debug(f'frame contour not filled enough')
            self.log.debug(f'imgH, imgW = {imgH}, {imgW}')
            self.log.debug(f'cntH, cntW = {cntH}, {cntW}')
            self.log.debug(f'fillRatio = {fillRatio}')
            return None

        return approxFrameContour.reshape(4, 2)

class LineBasedFrameFinder():
    """
    A processor that takes an image which presumably contains a ProductSheet printed on white
    paper as input and identifies the contour of the bold frame on it.

    :class:`LineBasedFrameFinder` finds frames even if they are not complete,
    but gets confused by sheet boundaries if the sheet is not well detected.

    :param name: name of the processor, used to identify logs and debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    :param minLineLength: Minimum length of line. Line segments shorter than
        this are rejected
    :type minLineLength: int
    :param maxLineGap: Maximum allowed gap between line segments to treat them
        as single line
    :type maxLineGap: int
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False,
                 log = helpers.Log(),
                 minLineLength = 800,
                 maxLineGap = 5):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.log = log
        self.pixelAccuracy = 1
        self.rotationAccuracy = np.pi/90
        self.threshold = 100
        self.minLineLength = minLineLength
        self.maxLineGap = maxLineGap

    @property
    def __prefix(self):
        """
        Prefix string to prepend before debug image names
        """
        return f'{self.tmpDir}{self.name}'

    def process(self, inputImg):
        """
        Identify the frame of a ProductSheet

        :param inputImg: image of a product sheet
        :type inputImg: BGR image
        :return: contour of the bounding rectangle of the frame, or None if
            no sensible contour could be found
        :rtype: list of four points ([int, int] each) or None
        """

        frameImg = np.copy(inputImg)
        grayImg = cv.cvtColor(inputImg,cv.COLOR_BGR2GRAY)
        blurredImg = cv.GaussianBlur(grayImg, (7, 7), 3)
        thresholdImg = cv.adaptiveThreshold(blurredImg, 255,
                cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY, 11, 2)
        thresholdImg = cv.bitwise_not(thresholdImg)
        dilationKernel = cv.getStructuringElement(cv.MORPH_RECT, (5, 5))
        dilatedImg = cv.dilate(thresholdImg, dilationKernel, 1)

        linesImg = np.copy(inputImg)
        lines = cv.HoughLinesP(dilatedImg, self.pixelAccuracy,
                self.rotationAccuracy, self.threshold,
                self.maxLineGap, self.minLineLength)

        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_0_gray.jpg', grayImg)
            cv.imwrite(f'{self.__prefix}_1_blurred.jpg', blurredImg)
            cv.imwrite(f'{self.__prefix}_2_threshold.jpg', thresholdImg)
            cv.imwrite(f'{self.__prefix}_3_dilated.jpg', dilatedImg)

        if lines is None:
            self.log.debug('Failed to find lines, not cropping image')
            return None

        corners = []
        for line in lines:
            x0,y0,x1,y1 = line[0]
            corners.append([x0, y0])
            corners.append([x1, y1])
            if self.writeDebugImages:
                cv.line(linesImg, (x0, y0), (x1, y1), (255, 0, 0), 2)

        boundingRect = cv.minAreaRect(np.array(corners))
        boundingRectCnt = np.int0(cv.boxPoints(boundingRect))
        cv.drawContours(linesImg,[boundingRectCnt], 0, (0, 255, 0), 4)

        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_4_linesImg.jpg', linesImg)

        imgH, imgW, _ = inputImg.shape
        _, (cntW, cntH), _ = boundingRect
        fillRatio = (cntW * cntH) / (imgW * imgH)
        if fillRatio < .25:
            self.log.debug(f'frame contour not filled enough')
            self.log.debug(f'imgH, imgW = {imgH}, {imgW}')
            self.log.debug(f'cntH, cntW = {cntH}, {cntW}')
            self.log.debug(f'fillRatio = {fillRatio}')
            return None

        return boundingRectCnt

class SheetNormalizer():
    """
    A processor that takes an image and the contour of the frame of a ProductSheet on it,
    transforms it back to represent the original ProductSheet as closely as
    possible.

    :param name: name of the processor, used to identify logs and debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False,
                 log = helpers.Log(),
                 ):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.log = log

        (frameP0, frameP1) = ProductSheet.getSheetFramePts()
        self.xMargin, self.yMargin = frameP0
        self.wMargin, self.hMargin = np.subtract(frameP1, frameP0)

    @property
    def __prefix(self):
        """
        Prefix string to prepend before debug image names
        """
        return f'{self.tmpDir}{self.name}'

    def process(self, inputImg, frameContour):
        """
        Normalize ProductSheet printed on inputImg.

        :param inputImg: image with a ProductSheet printed on it
        :type inputImg: BGR image
        :param frameContour: four-point contour of the frame of the
            ProductSheet
        :type frameContour: list of four points ([int, int] each)
        :return: normalized image of the ProductSheet
        :rtype: BGR image
        """
        rectifiedImg = self.__fourPointTransform(inputImg, frameContour)

        resizedImg = cv.resize(rectifiedImg, (self.wMargin, self.hMargin))
        outputImg = cv.copyMakeBorder(resizedImg,
                self.yMargin,
                self.yMargin,
                self.xMargin,
                self.xMargin,
                cv.BORDER_CONSTANT,
                value=(255,255,255))

        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_5_rectified.jpg', rectifiedImg)
            cv.imwrite(f'{self.__prefix}_6_resizedImg.jpg', resizedImg)
            cv.imwrite(f'{self.__prefix}_7_output.jpg', outputImg)

        return outputImg

    def __fourPointTransform(self, image, corners):
        """
        Perspective transform of a contour with four points on an input image
        to 'birds eye view' by https://www.pyimagesearch.com/

        :param image: image to be transformed, all corners must fit inside
        :type image: BGR image
        :param corners: corner points of the contour
        :type corners: list of four points ([int, int] each)
        :return: transformed image
        :rtype: BGR image
        """
        # obtain a consistent order of the points
        rect = self.__orderPoints(corners)
        (topLeft, topRight, bottomRight, bottomLeft) = rect

        # compute the width of the new image
        widthA = self.__pointDistance(bottomRight, bottomLeft)
        widthB = self.__pointDistance(topRight, topLeft)
        maxWidth = max(int(widthA), int(widthB))

        # compute the height of the new image
        heightA = self.__pointDistance(topRight, bottomRight)
        heightB = self.__pointDistance(topLeft, bottomLeft)
        maxHeight = max(int(heightA), int(heightB))

        # now that we have the dimensions of the new image, construct
        # the set of destination points to obtain a "birds eye view",
        # (i.e. top-down view) of the image, again specifying points
        # in the top-left, top-right, bottom-right, and bottom-left
        # order
        dst = np.array([
                [0, 0],
                [maxWidth - 1, 0],
                [maxWidth - 1, maxHeight - 1],
                [0, maxHeight - 1]], dtype = "float32")

        # compute the perspective transform matrix and then apply it
        M = cv.getPerspectiveTransform(rect, dst)
        warped = cv.warpPerspective(image, M, (maxWidth, maxHeight))
        return warped

    def __orderPoints(self, pts):
        """
        Order points into top-left, top-right, bottom-right, bottom-left order

        :param pts: corner points
        :type pts: list of four points ([int, int] each)
        :return: list of points in consistent order
        :rtype: list of four points ([int, int] each)
        """
        # initialzie a list of coordinates that will be ordered
        # such that the first entry in the list is the top-left,
        # the second entry is the top-right, the third is the
        # bottom-right, and the fourth is the bottom-left
        rect = np.zeros((4, 2), dtype = "float32")
        # the top-left point will have the smallest sum, whereas
        # the bottom-right point will have the largest sum
        s = pts.sum(axis = 1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        # now, compute the difference between the points, the
        # top-right point will have the smallest difference,
        # whereas the bottom-left will have the largest difference
        diff = np.diff(pts, axis = 1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        # return the ordered coordinates
        return rect

    def __pointDistance(self, pt0, pt1):
        """
        Compute the distance between two points
        :param pt0: first point
        :type pt0: [int, int]
        :param pt1: second point
        :type pt1: [int, int]
        :return: distance between first and second point
        :rtype: float
        """
        return np.sqrt(((pt0[0] - pt1[0]) ** 2) + ((pt0[1] - pt1[1]) ** 2))

class TagRecognizer():
    """
    A processor that takes  a normalized image of a ProductSheet and tries to
    recognize all boxes on it

    :param name: name of the processor, used to identify logs and debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param db: database with possible box values and configurations
    :type db: class: `database.Database`
    :param tesseractApi: API interface to tesseract
    :type tesseractApi: class `tesserocr.PyTessBaseAPI`
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    :param searchMarginSize: margin by which each box image is extended to look
        for its actual corners
    :type searchMarginSize: int
    :param borderSize: Size of the border of a box that is discarded. When the
        actual corners of a box are identified, their bounding rectangle is cropped
        by borderSize to only consider the area inside the box for ocr
    :type borderSize: int
    :param minplausibleboxsize: Minimal size of a box to be considered
        sucessfully detected. If the area identified as being inside the box is
        smaller than this, identification is considered to have failed.
    :type minPlausibleBoxSize: int
    :param minComponentArea: Minimal size of a component to be considered for
        OCR (aka minimal expected letter size). If a single component inside the
        box is smaller than this, it is clipped away before OCR.
    :type minComponentArea: int
    :param minAspectRatio: Minimal aspect ratio of a component to be considered for
        OCR. Long, thin components are discarded if
        min(height, width) / max(height, width) < minAspectRatio
    :type minAspectRatio: int
    :param confidenceThreshold: Minimal confidence needed to color the
        recognized box text as 'safely recognized' in the debug output image.
        For confidence calculation, check `self.__findClosestString`
    :type confidenceThreshold: float
    """
    def __init__(self,
            name,
            tmpDir,
            db,
            tesseractApi,
            writeDebugImages = False,
            log = helpers.Log(),
            searchMarginSize = 25,
            borderSize = 5,
            minPlausibleBoxSize = 1000,
            minComponentArea = 100,
            minAspectRatio = .2,
            confidenceThreshold = 0.5
            ):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.log = log
        self.searchMarginSize = searchMarginSize
        self.borderSize = borderSize
        self.minPlausibleBoxSize = minPlausibleBoxSize
        self.minComponentArea = minComponentArea
        self.minAspectRatio = minAspectRatio
        self.confidenceThreshold = confidenceThreshold
        self.tesseractApi = tesseractApi
        self.__db = db
        self.__sheet = ProductSheet()

        # prepare choices
        maxNumSheets = self.__db.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')
        sheetNumberString = self.__db.config.get('tagtrail_gen',
                'sheet_number_string')
        self.__sheetNumberCandidates = [
                sheetNumberString.format(sheetNumber=str(n)).upper()
                for n in range(1, maxNumSheets+1)]
        self.log.debug(f'sheetNumberCandidates={list(self.__sheetNumberCandidates)}')

        self.__productNameCandidates = [p.description.upper()
                for p in self.__db.products.values()]
        self.log.debug(f'productNameCandidates={list(self.__productNameCandidates)}')

        self.__unitCandidates = [p.amountAndUnit.upper()
                for p in self.__db.products.values()]
        self.log.debug(f'unitCandidates={list(self.__unitCandidates)}')

        self.currency = self.__db.config.get('general', 'currency')
        self.__priceCandidates = [
                helpers.formatPrice(p.grossSalesPrice(), self.currency).upper()
                for p in self.__db.products.values()]
        self.log.debug(f'priceCandidates={list(self.__priceCandidates)}')

        self.__memberIdCandidates = [m.id for m in self.__db.members.values()]
        self.log.debug(f'memberIdCandidates={list(self.__memberIdCandidates)}')

    def productId(self):
        """
        Recognized productId
        """
        return self.__sheet.productId()

    def sheetNumber(self):
        """
        Recognized sheet number. If recognition failed or is not yet done, a
        fallback is returned.
        """
        return self.__sheet.sheetNumber

    def fileName(self):
        """
        Recognized file name. If recognition failed or is not yet done, a
        fallback is returned.
        """
        return self.__sheet.fileName()

    @property
    def __prefix(self):
        """
        Prefix string to prepend before debug image names
        """
        return f'{self.tmpDir}{self.name}'

    def process(self, inputImg, fallbackSheetName, fallbackSheetNumber):
        """
        Recognize box texts (tags and product information) on an image. The
        recognized ProductSheet can be stored and name / sheet number
        queried after process completed.

        :param inputImg: normalized image of a printed out ProductSheet with
            member tags on it
        :type inputImg: BGR image
        :param fallbackSheetName: fallback name to be able to store the sheet
            if OCR of the name failed; must be unique when concatenated with
            fallbackSheetNumber
        :type fallbackSheetName: str
        :type fallbackSheetNumber: fallback number to be able to store the
            sheet if OCR of the sheet number failed; must be unique when
            concatenated with fallbackSheetName
        :type fallbackSheetNumber: int
        """
        self.__inputImg = inputImg
        self.__grayImg = cv.cvtColor(inputImg,cv.COLOR_BGR2GRAY)
        self.__blurredImg = cv.GaussianBlur(self.__grayImg, (7, 7), 3)
        self.__grayImg = np.float32(self.__grayImg)

        self._recognizedBoxTexts = {}
        for box in self.__sheet.boxes():
            if box.name == "nameBox":
                name, confidence = self.__recognizeBoxText(box, self.__productNameCandidates)
                if name == '' or confidence < 0.5:
                    box.text, box.confidence = fallbackSheetName, 0
                else:
                    box.text, box.confidence = name, confidence
            elif box.name == "unitBox":
                box.text, box.confidence = self.__recognizeBoxText(box, self.__unitCandidates)
                if box.text == '':
                    box.confidence = 0
            elif box.name == "priceBox":
                box.text, box.confidence = self.__recognizeBoxText(box, self.__priceCandidates)
                if box.text == '' or confidence < 1:
                    box.confidence = 0
            elif box.name == "sheetNumberBox":
                sheetNumber, confidence = self.__recognizeBoxText(box,
                        self.__sheetNumberCandidates)
                if sheetNumber == '' or confidence < 1:
                    box.text, box.confidence = str(fallbackSheetNumber), 0
                else:
                    box.text, box.confidence = sheetNumber, confidence
            elif box.name.find("dataBox") != -1:
                box.text, box.confidence = self.__recognizeBoxText(box, self.__memberIdCandidates)
            else:
                box.text, box.confidence = ("", 1.0)

        # try to fill in product infos if id is clear
        nameBox = self.__sheet.boxByName('nameBox')
        unitBox = self.__sheet.boxByName('unitBox')
        priceBox = self.__sheet.boxByName('priceBox')
        sheetNumberBox = self.__sheet.boxByName('sheetNumberBox')
        if nameBox.confidence == 1:
            product = self.__db.products[self.__sheet.productId()]
            expectedAmountAndUnit = product.amountAndUnit.upper()
            expectedPrice = helpers.formatPrice(product.grossSalesPrice(),
                    self.currency).upper()
            if unitBox.confidence < 1:
                self.log.info(f'Inferred unit={expectedAmountAndUnit}')
                unitBox.text = expectedAmountAndUnit
                unitBox.confidence = 1
            elif unitBox.text != expectedAmountAndUnit:
                unitBox.confidence = 0
            if priceBox.confidence < 1:
                self.log.info(f'Inferred price={expectedPrice}')
                priceBox.text = expectedPrice
                priceBox.confidence = 1
            elif priceBox.text != expectedPrice:
                priceBox.confidence = 0
            if (product.previousQuantity < ProductSheet.maxQuantity()
                    and sheetNumberBox.text == ''):
                # previousQuantity might also be small because many units were
                # already sold, while we still have more than one sheet
                # => this is just a good guess
                sheetNumberBox.confidence = 0
                sheetNumberBox.text = self.__db.config.get('tagtrail_gen',
                        'sheet_number_string').format(sheetNumber='1')
                self.log.info(f'Inferred sheetNumber={sheetNumberBox.text}')

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

        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_1_outputImage.jpg', self.__sheet.createImg())

    def __recognizeBoxText(self, box, candidateTexts):
        """
        Run the box region of the processed image through OCR to identify and
        assign text to the box.

        :return: (text, confidence) of the best match among candidateTexts
        :rtype: (str, float), where 0 <= float <= 1 and str in candidateTexts
        """
        (x0, y0), (x1, y1) = self.__findBoxContour(box)
        if (x1 - x0) * (y1 - y0) < self.minPlausibleBoxSize:
            box.bgColor = (0, 0, 80)
            return ("", 0.0)

        boxInputImg = self.__inputImg[y0:y1, x0:x1]
        blurredImg = self.__blurredImg[y0:y1, x0:x1]
        thresholdImg = cv.adaptiveThreshold(blurredImg, 255,
                cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY,11,2)
        thresholdImg = cv.bitwise_not(thresholdImg)
        openingKernel = cv.getStructuringElement(cv.MORPH_RECT, (2,2))
        openedImg = cv.erode(thresholdImg, openingKernel, iterations = 1)
        closingKernel = cv.getStructuringElement(cv.MORPH_RECT, (5,5))
        closedImg = cv.dilate(openedImg, closingKernel, iterations = 1)
        numComponents, labeledImg, stats, _ = cv.connectedComponentsWithStats(closedImg)

        # remove spurious components
        height, width = labeledImg.shape
        maxComponentArea = height * width / 4
        cleanedImg = np.zeros(labeledImg.shape, dtype="uint8")
        boundingRectImg = boxInputImg.copy()
        for label in range(numComponents):
            self.log.debug(f'stats[label, cv.CC_STAT_AREA]={stats[label, cv.CC_STAT_AREA]}')
            if stats[label, cv.CC_STAT_AREA] < self.minComponentArea:
                self.log.debug('component removed, too small')
                continue

            if maxComponentArea < stats[label, cv.CC_STAT_AREA]:
                self.log.debug('component removed, too big')
                continue

            componentWidth = stats[label, cv.CC_STAT_WIDTH]
            componentHeight = stats[label, cv.CC_STAT_HEIGHT]
            aspectRatio = (min(componentWidth, componentHeight) /
                    max(componentWidth, componentHeight))
            self.log.debug(f'stats[label, cv.CC_STAT_WIDTH]={componentWidth}')
            self.log.debug(f'stats[label, cv.CC_STAT_HEIGHT]={componentHeight}')
            self.log.debug(f'aspectRatio={aspectRatio}')
            if aspectRatio < self.minAspectRatio:
                continue

            mask = np.where(labeledImg == label, np.uint8(255.0),
                    np.uint8(0.0))
            x, y, w, h = cv.boundingRect(mask)
            boundingRectArea = w * h
            if maxComponentArea < boundingRectArea:
                self.log.debug(f'component removed, boundingRect too big {w*h}')
                continue

            boundingRectFillFactor = stats[label, cv.CC_STAT_AREA] / boundingRectArea
            if boundingRectFillFactor < 0.35:
                self.log.debug(f'boundingRectFillFactor = {boundingRectFillFactor}')
                self.log.debug('component removed, too sparsly filled')
                continue
            elif self.writeDebugImages:
                cv.rectangle(boundingRectImg, (x, y), (x+w, y+h), (255,0,0), 2)

            # label marks a real component
            cleanedImg = np.where(labeledImg == label, np.uint8(255.0),
                    cleanedImg)

        closingKernel = cv.getStructuringElement(cv.MORPH_RECT,
                (18, 12))
        closedImg2 = cv.morphologyEx(cleanedImg, cv.MORPH_CLOSE,
                closingKernel)

        dilationKernel = cv.getStructuringElement(cv.MORPH_RECT,
                (5, 5))
        dilatedImg = cv.dilate(closedImg2, dilationKernel, 1)

        if self.writeDebugImages:
            labeledImg = labeledImg / numComponents * 255
            cv.imwrite(f'{self.__prefix}_{box.name}_01_boxInputImg.jpg', boxInputImg)
            cv.imwrite(f'{self.__prefix}_{box.name}_02_thresholdImg.jpg', thresholdImg)
            cv.imwrite(f'{self.__prefix}_{box.name}_03_openedImg.jpg', openedImg)
            cv.imwrite(f'{self.__prefix}_{box.name}_04_closedImg.jpg', closedImg)
            cv.imwrite(f'{self.__prefix}_{box.name}_05_labeledImg.jpg', labeledImg)
            cv.imwrite(f'{self.__prefix}_{box.name}_06_boundingRectImg.jpg', boundingRectImg)
            cv.imwrite(f'{self.__prefix}_{box.name}_07_cleanedImg.jpg', cleanedImg)
            cv.imwrite(f'{self.__prefix}_{box.name}_08_closedImg2.jpg', closedImg2)
            cv.imwrite(f'{self.__prefix}_{box.name}_09_dilatedImg.jpg', dilatedImg)

        # find contours in the thresholded cell
        cnts = cv.findContours(dilatedImg.copy(), cv.RETR_EXTERNAL,
                cv.CHAIN_APPROX_SIMPLE)
        cnts = imutils.grab_contours(cnts)
        # if no contours were found than this is an empty cell
        if len(cnts) == 0:
            box.bgColor = (255, 0, 0)
            return ("", 1.0)

        # otherwise, take all contours that increase the percentage of
        # white/black pixels
        maskImg = np.zeros(dilatedImg.shape, dtype="uint8")
        commonBoundingRect = None
        commonArea = 0
        sortedContours = sorted(cnts, key=cv.contourArea, reverse=True)
        for idx, cnt in enumerate(sortedContours):
            boundingRect = cv.boundingRect(cnt) # x, y, w, h
            x2 = boundingRect[0] + boundingRect[2]
            y2 = boundingRect[1] + boundingRect[3]
            area = boundingRect[2]*boundingRect[3]
            if commonBoundingRect is None:
                commonBoundingRect = boundingRect
                commonArea = area
                cv.drawContours(maskImg, [cnt], -1, 255, -1)
            else:
                commonX2 = commonBoundingRect[0] + commonBoundingRect[2]
                commonY2 = commonBoundingRect[1] + commonBoundingRect[3]

                newCommonX = min(boundingRect[0], commonBoundingRect[0])
                newCommonY = min(boundingRect[1], commonBoundingRect[1])
                newCommonBoundingRect = (newCommonX,
                        newCommonY,
                        max(x2, commonX2) - newCommonX,
                        max(y2, commonY2) - newCommonY)
                newCommonArea = newCommonBoundingRect[2]*newCommonBoundingRect[3]
                if( area / (newCommonArea - commonArea + 1) > 0.5):
                    commonBoundingRect = newCommonBoundingRect
                    cv.drawContours(maskImg, [cnt], -1, 255, -1)
        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_{box.name}_08_maskImg.jpg', maskImg)

        centerX = commonBoundingRect[0] + commonBoundingRect[2] / 2
        centerY = commonBoundingRect[1] + commonBoundingRect[3] / 2
        h, w = maskImg.shape
        minBorderDist = 20
        if centerX < minBorderDist or w - minBorderDist < centerX or centerY < minBorderDist or h - minBorderDist < centerY:
            self.log.debug(f'{box.name} centerX = {centerX}, centerY = {centerY}')
            self.log.debug(f'{box.name} too close to border, h = {h}, w = {w}')
            box.bgColor = (255, 0, 0)
            return ("", 1.0)

        # compute the percentage of masked pixels relative to the total
        # area of the image
        (h, w) = maskImg.shape
        percentFilled = cv.countNonZero(maskImg) / float(w * h)
        # if less than 3% of the mask is filled then we are looking at
        # noise and can safely ignore the contour
        if percentFilled < 0.03:
            self.log.debug(f'not filled enough, percentFilled = {percentFilled}')
            box.bgColor = (255, 0, 0)
            return ("", 1.0)

        p = RotateLabel(f'_{box.name}_09_rotation', self.__prefix,
                writeDebugImages = self.writeDebugImages, log=self.log)
        ocrImg = p.process(maskImg, boxInputImg)
        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_{box.name}_10_ocrImage.jpg', ocrImg)

        self.tesseractApi.SetImage(Image.fromarray(ocrImg))
        ocrText = self.tesseractApi.GetUTF8Text().strip()

        confidence, text = self.__findClosestString(ocrText.upper(), candidateTexts)
        self.log.info("(ocrText, confidence, text) = ({}, {}, {})", ocrText, confidence, text)
        return (text, confidence)

    def __findBoxContour(self, box):
        """
        Finds the actual contour of the given box on the processed image.

        :param box: the box to be recognized, giving an initial estimate of the
            position
        :type box: class: `sheets.Box`
        :return: Position of the upper left and lower right corner of the box
            on the processed image, [[upperLeftX, upperLeftY], [lowerLeftX, lowerLeftY]]
        """
        (initX0,initY0),(initX1,initY1)=box.pt1,box.pt2

        # look for the corners of our box in an extended area around the region
        # the box should have been orginally printed in
        extendedX0 = initX0-self.searchMarginSize
        extendedX1 = initX1+self.searchMarginSize
        extendedY0 = initY0-self.searchMarginSize
        extendedY1 = initY1+self.searchMarginSize
        cornerImg = np.copy(self.__grayImg[extendedY0:extendedY1,
            extendedX0:extendedX1])
        harrisDst = cv.cornerHarris(cornerImg, 9, 3, 0.04)
        _, harrisDst = cv.threshold(harrisDst, 0.01*harrisDst.max(), 255, 0)

        # find corner centroids
        _, _, _, centroids = cv.connectedComponentsWithStats(
                np.uint8(harrisDst))
        centroids = np.int0(centroids)
        xs = [pt[0] for pt in centroids]
        ys = [pt[1] for pt in centroids]
        cornerX0, cornerX1 = min(xs), max(xs)
        cornerY0, cornerY1 = min(ys), max(ys)

        if self.writeDebugImages:
            cv.circle(cornerImg, (cornerX0, cornerY0), 5, 255, 5)
            cv.circle(cornerImg, (cornerX1, cornerY0), 5, 255, 5)
            cv.circle(cornerImg, (cornerX0, cornerY1), 5, 255, 5)
            cv.circle(cornerImg, (cornerX1, cornerY1), 5, 255, 5)
            cv.imwrite(f'{self.__prefix}_{box.name}_00_cornerImg.jpg', cornerImg)

        return [
                [extendedX0 + cornerX0 + self.borderSize,
                   extendedY0 + cornerY0 + self.borderSize],
                [extendedX0 + cornerX1 - self.borderSize,
                    extendedY0 + cornerY1 - self.borderSize]
                ]

    def __findClosestString(self, searchString, candidateStrings):
        """
        Find the best match for searchString among candidateStrings

        :param searchString: string to search for
        :type searchString: string
        :param candidateStrings: list of str
        :type candidateStrings: list of str
        :return: (confidence, match) of the best match, where
            0 <= confidence <= 1 and match is one of candidateStrings.
            Confidence is calculated as 1 - minDist / secondDist, where minDist
        :rtype: (str, float)
        """
        candidateStrings=list(set(candidateStrings))
        self.log.debug(f"findClosestString: searchString={searchString}")
        self.log.debug(f"findClosestString: candidateStrings={candidateStrings}")
        dists = list(map(lambda x: Levenshtein.distance(x, searchString), candidateStrings))
        self.log.debug("dists={}", dists)
        minDist, secondDist = np.partition(dists, 1)[:2]
        if minDist > 5 or minDist == secondDist:
            return 0, ""
        confidence = 1 - minDist / secondDist
        return confidence, candidateStrings[dists.index(minDist)]

    def resetSheetToFallback(self, fallbackSheetName, fallbackSheetNumber):
        """
        Reset the sheet to a unique fallback name / number
        """
        self.__sheet.name = fallbackSheetName
        self.__sheet.sheetNumber = fallbackSheetNumber

    def storeSheet(self, outputDir):
        """
        Store the recognized sheet as f'{outputDir}{self.fileName()}

        :param outputDir: directory to store the csv file to
        :type outputDir: str
        :raises ValueError: if the file already exists and would be overwritten
        """
        if os.path.exists(f'{outputDir}{self.fileName()}'):
            raise ValueError(
                f'{outputDir}{self.fileName()} already exists')
        self.__sheet.store(outputDir)

class RotateLabel():
    """
    A processor that takes a mask and original image of a label, identifies the
    bounding rectangle of all contours on the mask and returns the original
    image cropped to the bounding rectangle and rotated to be horizontal.

    :param name: name of the processor, used to identify logs and debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False,
                 log = helpers.Log()):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.log = log
        self.borderSize = 20

    def process(self, maskImg, originalImg):
        """
        Crop and rotate the label contours

        :param maskImg: image where all label contours are in white
        :type maskImg: black/white image
        :param originalImg: original scanned image of the label, same size as maskImg
        :type originalImg: BGR image
        :return: warped sub-image of the originalImg, where the masked label is
            cropped and rotated to be horizontal
        :rtype: BGR image
        """
        maskImg = cv.copyMakeBorder(maskImg, self.borderSize,
                self.borderSize, self.borderSize, self.borderSize,
                cv.BORDER_CONSTANT, value=(0, 0, 0))
        originalImg = cv.copyMakeBorder(originalImg, self.borderSize,
                self.borderSize, self.borderSize, self.borderSize,
                cv.BORDER_CONSTANT, value=(0, 0, 0))

        # find minAreaRect of joint contours
        contours, _ = cv.findContours(maskImg, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        joinedContour = np.vstack(contours)
        minAreaRect = cv.minAreaRect(joinedContour)
        center, (minAreaRectWidth, minAreaRectHeight), rotationAngle = minAreaRect

        # extract the rotated minAreaRect from the original
        # cudos to http://felix.abecassis.me/2011/10/opencv-rotation-deskewing/
        if rotationAngle < -45.0:
            rotationAngle += 90.0
            minAreaRectWidth, minAreaRectHeight = minAreaRectHeight, minAreaRectWidth
        rotationMatrix = cv.getRotationMatrix2D(center, rotationAngle, 1.0)

        originalImgHeight, originalImgWidth, _ = originalImg.shape
        rotatedImg = cv.warpAffine(originalImg, rotationMatrix, (originalImgWidth, originalImgHeight), flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)
        outputImg = cv.getRectSubPix(rotatedImg, (int(minAreaRectWidth), int(minAreaRectHeight)), center)

        if self.writeDebugImages:
            minAreaImg = cv.cvtColor(np.copy(maskImg), cv.COLOR_GRAY2BGR)
            cv.drawContours(minAreaImg,[np.int0(cv.boxPoints(minAreaRect))],0,(0,0,255),2)
            minAreaImgHeight, minAreaImgWidth, _ = minAreaImg.shape
            minAreaRotatedImg = cv.warpAffine(minAreaImg, rotationMatrix, (minAreaImgWidth, minAreaImgHeight), flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)

            cv.imwrite(f'{self.tmpDir}{self.name}_0_input.jpg', maskImg)
            cv.imwrite(f'{self.tmpDir}{self.name}_1_minArea.jpg', minAreaImg)
            cv.imwrite(f'{self.tmpDir}{self.name}_2_minAreaRotated.jpg', minAreaRotatedImg)
            cv.imwrite(f'{self.tmpDir}{self.name}_3_output.jpg', outputImg)

        return outputImg

class SplitSheetDialog(Dialog):
    initialScreenPercentage = 0.75

    """
    A dialog to correct wrongly split sheets before OCR.
    """
    def __init__(self,
            root,
            inputImg,
            model):
        self.inputImg = inputImg
        self.model = model
        self.log = self.model.log
        self.outputImg = None
        self.isEmpty = False
        self.__selectedCorners = []
        super().__init__(root)

    def body(self, master):
        self.width=master.winfo_screenwidth() * self.initialScreenPercentage
        self.height=master.winfo_screenheight() * self.initialScreenPercentage
        o_h, o_w, _ = self.inputImg.shape
        aspectRatio = min(self.height / o_h, self.width / o_w)
        canvas_h, canvas_w = int(o_h * aspectRatio), int(o_w * aspectRatio)
        resizedImg = cv.resize(self.inputImg, (canvas_w, canvas_h), Image.BILINEAR)
        self.resizedImg = ImageTk.PhotoImage(Image.fromarray(resizedImg))
        self.log.debug(f'canvas_w, canvas_h = {canvas_w}, {canvas_h}')

        self.canvas = tkinter.Canvas(master,
               width=canvas_w,
               height=canvas_h)
        self.canvas.bind("<Button-1>", self.onMouseDown)
        self.canvas.bind("<Motion>", self.onMouseMotion)
        self.canvas.pack()
        self.resetCanvas(None, None)
        return None

    def buttonbox(self):
        box = tkinter.Frame(self)

        w = tkinter.Button(box, text="OK", width=10, command=self.ok,
                default=tkinter.ACTIVE)
        w.pack(side=tkinter.LEFT, padx=5, pady=5)
        w = tkinter.Button(box, text="Cancel", width=10, command=self.cancel)
        w.pack(side=tkinter.LEFT, padx=5, pady=5)
        w = tkinter.Button(box, text="Empty sheet", width=10, command=self.markEmpty)
        w.pack(side=tkinter.LEFT, padx=5, pady=5)

        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

        box.pack()

    def markEmpty(self):
        self.isEmpty = True
        self.ok()

    def apply(self):
        if len(self.__selectedCorners) == 2:
            self.update()
            canvasW = self.canvas.winfo_width()
            canvasH = self.canvas.winfo_height()
            imgH, imgW, _ = self.inputImg.shape

            x0 = int(self.__selectedCorners[0][0] / canvasW * imgW)
            y0 = int(self.__selectedCorners[0][1] / canvasH * imgH)
            x1 = int(self.__selectedCorners[1][0] / canvasW * imgW)
            y1 = int(self.__selectedCorners[1][1] / canvasH * imgH)
            img = self.inputImg[y0:y1, x0:x1, :]

            frameContour = LineBasedFrameFinder(
                    'sheetDetector',
                    self.model.tmpDir,
                    self.model.writeDebugImages,
                    self.log
                    ).process(img)

            if frameContour is None:
                self.log.debug(f'no frame contour found, take user specified')
                self.outputImg = img.copy()
            else:
                self.outputImg = SheetNormalizer(
                        'normalizer',
                        self.model.tmpDir,
                        self.model.writeDebugImages,
                        self.log
                        ).process(img, np.array(frameContour))

    def onMouseDown(self, event):
        if len(self.__selectedCorners) < 2:
            self.__selectedCorners.append([event.x, event.y])
        else:
            self.__selectedCorners = [[event.x, event.y]]

        self.resetCanvas(event.x, event.y)

    def onMouseMotion(self, event):
        self.resetCanvas(event.x, event.y)

    def resetCanvas(self, x, y):
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tkinter.NW, image=self.resizedImg)

        self.update()
        canvasWidth = self.canvas.winfo_width()
        canvasHeight = self.canvas.winfo_height()

        if len(self.__selectedCorners) == 1:
            self.canvas.create_rectangle(
                    self.__selectedCorners[0][0],
                    self.__selectedCorners[0][1],
                    x,
                    y,
                    outline = 'green',
                    width = 4)

        if len(self.__selectedCorners) == 2:
            self.canvas.create_rectangle(
                    self.__selectedCorners[0][0],
                    self.__selectedCorners[0][1],
                    self.__selectedCorners[1][0],
                    self.__selectedCorners[1][1],
                    outline = 'green',
                    width = 4)

class SheetRegionData():
    """
    A simple data class holding metadata of a sheet region on a scanned image

    :param inputScanFilepath: path of the scan the sheet was recognized on
    :type inputScanFilepath: str
    :param name: unique name of the sheet
    :type name: str
    :param tmpDir: temporary directory where debug images of the sheet are
        stored
    :type tmpDir: str
    :param unprocessedImg: original cropped image, without further processing
    :type unprocessedImg: BGR image
    :param processedImg: normalized image of the sheet, ready for OCR
    :type processedImg: BGR image
    :param isEmpty: `True` if the sheet region is considered empty
    :type isEmpty: bool
    """
    def __init__(self,
            inputScanFilepath,
            name,
            tmpDir,
            unprocessedImg,
            processedImg,
            isEmpty
            ):
        self.inputScanFilepath=inputScanFilepath
        self.name=name
        self.tmpDir=tmpDir
        self.unprocessedImg=unprocessedImg
        self.processedImg=processedImg
        self.isEmpty=isEmpty

class Model():
    """
    Model class exposing all functionality needed to process scanned
    ProductSheets and store their content as .csv files.

    :param tmpDir: temporary directory to write debug images to
    :type tmpDir: str
    :param scanDir: directory where the scan files are stored
    :type scanDir: str
    :param outputDir: directory to write ProductSheet .csv files to
    :type outputDir: str
    :param scanFilenames: list of filenames (input scans) to be processed
    :type scanFilenames: list of str
    :param db: database with products, members and configurations
    :type db: class: `database.Database`
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    """
    def __init__(self,
            tmpDir,
            scanDir,
            outputDir,
            scanFilenames,
            db,
            writeDebugImages = False,
            log = helpers.Log(helpers.Log.LEVEL_INFO)):
        self.tmpDir = tmpDir
        self.scanDir = scanDir
        self.outputDir = outputDir
        self.scanFilenames = scanFilenames
        self.db = db
        self.log = log
        self.writeDebugImages = writeDebugImages
        self.sheetRegions = []
        self.partiallyFilledFiles = set()
        self.compressedImgWidth = self.db.config.getint('tagtrail_ocr',
                'output_img_width')
        self.compressedImgQuality = self.db.config.getint('tagtrail_ocr',
                'output_img_jpeg_quality')
        self.tesseractApi = None

    def __enter__(self):
        self.tesseractApi = PyTessBaseAPI(psm=PSM.SINGLE_WORD)

    def __exit__(self, exc_type, exc_value, traceback):
        self.tesseractApi.End()
        self.tesseractApi = None

    def prepareScanSplitting(self):
        """
        Prepare to walk over self.scanFilenames and invoke self.splitScan with
        each of them. Any previously processed scans are discarded, and
        self.outputDir is emptied.
        """
        self.sheetRegions = []
        helpers.recreateDir(self.outputDir)
        self.fallbackSheetNumber = 0

    def splitScan(self, scanFilename, sheetCoordinates, rotationAngle):
        """
        Load a scanned image from scanFilename, split it into multiple sheet
        regions, process them and append the results to self.sheetRegions

        :param scanFilename: filename under self.scanDir of the scanned image to be loaded
        :type scanFilename: str
        :param sheetCoordinates: list of relative coordinates [x0, y0, x1, y1]
            for all four sheets on a scanned file, e.g.
            [[0,0,.5,.5], [.5, 0, 1, .5], [0, .5, .5, 1], [.5, .5, 1, 1]]
        :type sheetCoordinates: list of [float, float, float, float] with length 4
        :param rotationAngle: angle in degrees by which the scanned image
            should be rotated before processing
        :type rotationAngle: int, [0,359]
        """
        splitDir = f'{self.tmpDir}/{scanFilename}/'
        helpers.recreateDir(splitDir)

        splitter = ScanSplitter(
                f'0_splitSheets',
                splitDir,
                self.writeDebugImages,
                self.log,
                sheetCoordinates[0],
                sheetCoordinates[1],
                sheetCoordinates[2],
                sheetCoordinates[3]
                )

        inputImg = cv.imread(self.scanDir + scanFilename)
        if inputImg is None:
            self.log.warn(f'file {self.scanDir + scanFilename} could not be ' +
                    'opened as an image')
            return

        rotatedImg = imutils.rotate_bound(inputImg, rotationAngle)
        self.log.info(f'Splitting scanned file: {scanFilename}')
        splitter.process(rotatedImg)
        for idx, splitImg in enumerate(splitter.outputSheetImgs):
            sheetName = f'{scanFilename}_sheet{idx}'
            self.log.info(f'sheetName = {sheetName}')
            sheetTmpDir = f'{self.tmpDir}{sheetName}/'
            helpers.recreateDir(sheetTmpDir)
            if splitImg is None:
                self.sheetRegions.append(SheetRegionData(
                    self.scanDir + scanFilename,
                    sheetName,
                    sheetTmpDir,
                    splitter.unprocessedSheetImgs[idx],
                    self.crossedOutCopy(splitter.unprocessedSheetImgs[idx]),
                    True))
            else:
                self.sheetRegions.append(SheetRegionData(
                    self.scanDir + scanFilename,
                    sheetName,
                    sheetTmpDir,
                    splitter.unprocessedSheetImgs[idx],
                    splitImg,
                    False))

    def crossedOutCopy(self, img):
        """
        Creates a copy of the input image with a cross on it, to mark the sheet
        as empty

        :param img: image to be crossed out
        :type img: BGR image
        :return: crossed out copy of the image
        :rtype: BGR image
        """
        height, width, _ = img.shape
        outputImg = np.copy(img)
        cv.line(outputImg, (0, 0), (width, height), (255,0,0), 20)
        cv.line(outputImg, (0, height), (width, 0), (255,0,0), 20)
        return outputImg

    def recognizeTags(self, sheetRegion):
        """
        Recognize tags on a sheet region and write the results to
        self.outputDir, or add its parent scan to the set of
        self.partiallFilledFiles if the region is empty

        Note: this call has to be invoked in a with-statement, e.g.

        .. code-block:: python

            m = Model(...)
            with m:
                m.recognizeTags(...)

        :param sheetRegion: the region to be processed
        :type sheetRegion: class `SheetRegionData`
        """
        if self.tesseractApi is None:
            raise AssertionError('use this method in a with-block')

        if sheetRegion.isEmpty:
            self.partiallyFilledFiles.add(sheetRegion.inputScanFilepath)
            return

        fallbackSheetName = sheetRegion.name
        recognizer = TagRecognizer("4_recognizeText", sheetRegion.tmpDir, self.db,
                self.tesseractApi, writeDebugImages = self.writeDebugImages, log = self.log)
        recognizer.process(sheetRegion.processedImg, fallbackSheetName,
                self.fallbackSheetNumber)

        if os.path.exists(f'{self.outputDir}{recognizer.fileName()}'):
            self.log.info('reset sheetRegion to fallback, as ' +
                    f'{recognizer.fileName()} already exists')
            recognizer.resetSheetToFallback(fallbackSheetName,
                    self.fallbackSheetNumber)

        recognizer.storeSheet(self.outputDir)
        sheetRegion.name = recognizer.fileName()
        self.fallbackSheetNumber += 1

        cv.imwrite(f'{self.outputDir}{recognizer.fileName()}_original_scan.jpg',
                imutils.resize(sheetRegion.unprocessedImg, width=self.compressedImgWidth),
                [int(cv.IMWRITE_JPEG_QUALITY), self.compressedImgQuality])
        cv.imwrite(f'{self.outputDir}{recognizer.fileName()}_normalized_scan.jpg',
                imutils.resize(sheetRegion.processedImg, width=self.compressedImgWidth),
                [int(cv.IMWRITE_JPEG_QUALITY), self.compressedImgQuality])

class GUI(BaseGUI):
    previewColumnCount = 4
    buttonFrameWidth = 200
    previewScrollbarWidth = 20

    def __init__(self,
            model,
            db,
            log = helpers.Log(helpers.Log.LEVEL_INFO)):

        self.model = model
        self.db = db
        self.__selectedCorners = []
        self.sheetCoordinates = list(range(4))
        self.scanCanvas = None
        self.buttonFrame = None
        self.setActiveSheet(None)
        self.loadConfig()
        self.readyForTagRecognition = False

        width = db.config.getint('general', 'screen_width')
        width = None if width == -1 else width
        height = db.config.getint('general', 'screen_height')
        height = None if height == -1 else height
        super().__init__(width, height, log)

    def get_minsize(self):
        return (self.buttonFrameWidth + self.previewScrollbarWidth, 300)

    def rotateImage90(self):
        self.rotationAngle = (self.rotationAngle + 90) % 360
        self.populateRoot()

    def populateRoot(self):
        if self.scanCanvas is not None:
            self.scanCanvas.destroy()
        if self.buttonFrame is not None:
            self.buttonFrame.destroy()

        if self.model.scanFilenames == []:
            messagebox.showwarning('No scanned files',
                'No scanned files found, aborting program')
            self.abortProcess()
            return

        # canvas with first scan to configure rotation and select sheet areas
        scannedImg = cv.imread(self.model.scanDir + self.model.scanFilenames[0])
        rotatedImg = imutils.rotate_bound(scannedImg, self.rotationAngle)

        o_h, o_w, _ = rotatedImg.shape
        aspectRatio = min(self.height / o_h, (self.width - self.buttonFrameWidth - self.previewScrollbarWidth) / 3 / o_w)
        canvas_h, canvas_w = int(o_h * aspectRatio), int(o_w * aspectRatio)
        resizedImg = cv.resize(rotatedImg, (canvas_w, canvas_h), Image.BILINEAR)

        # Note: it is necessary to store the image locally for tkinter to show it
        self.resizedImg = ImageTk.PhotoImage(Image.fromarray(resizedImg))
        self.scanCanvas = tkinter.Canvas(self.root,
               width=canvas_w,
               height=canvas_h)
        self.scanCanvas.place(x=0, y=0)
        self.scanCanvas.bind("<Button-1>", self.onMouseDownOnScanCanvas)
        self.resetScanCanvas()

        # preview of split sheets with the current configuration
        self.previewCanvas = tkinter.Canvas(self.root,
               width=self.width - self.buttonFrameWidth - self.previewScrollbarWidth - canvas_w,
               height=self.height)
        self.previewCanvas.configure(scrollregion=self.previewCanvas.bbox("all"))
        self.previewCanvas.place(x=canvas_w, y=0)
        self.previewCanvas.bind('<Button-1>', self.onMouseDownOnPreviewCanvas)
        # with Windows OS
        self.previewCanvas.bind("<MouseWheel>", self.onMouseWheelPreviewCanvas)
        # with Linux OS
        self.previewCanvas.bind("<Button-4>", self.onMouseWheelPreviewCanvas)
        self.previewCanvas.bind("<Button-5>", self.onMouseWheelPreviewCanvas)
        self.scrollPreviewY = tkinter.Scrollbar(self.root, orient='vertical', command=self.previewCanvas.yview)
        self.scrollPreviewY.place(
                x=self.width - self.buttonFrameWidth - self.previewScrollbarWidth,
                y=0,
                width=self.previewScrollbarWidth,
                height=self.height)
        self.previewCanvas.configure(yscrollcommand=self.scrollPreviewY.set)

        self.root.update()
        scanHeight, scanWidth, _ = imutils.rotate_bound(
                cv.imread(self.model.scanDir + self.model.scanFilenames[0]),
                self.rotationAngle).shape
        self.previewColumnWidth, self.previewRowHeight = 0, 0
        for sheetCoords in self.sheetCoordinates:
            width = (sheetCoords[2] - sheetCoords[0]) * ScanSplitter.normalizedWidth
            height = (sheetCoords[3] - sheetCoords[1]) * ScanSplitter.normalizedHeight
            resizeRatio = self.previewCanvas.winfo_width() / (self.previewColumnCount * width)
            resizedWidth, resizedHeight = int(width * resizeRatio), int(height * resizeRatio)
            self.previewColumnWidth = max(self.previewColumnWidth, resizedWidth)
            self.previewRowHeight = max(self.previewRowHeight, resizedHeight)

        self.resetPreviewCanvas()

        # Additional buttons
        self.buttonFrame = tkinter.Frame(self.root,
               width=self.buttonFrameWidth,
               height=canvas_h)
        self.buttonFrame.place(x=self.width - self.buttonFrameWidth, y=0)
        self.buttons = {}

        self.buttons['loadConfig'] = tkinter.Button(self.buttonFrame, text='Load configuration',
            command=self.loadConfigAndResetGUI)
        self.buttons['loadConfig'].bind('<Return>', self.loadConfigAndResetGUI)
        self.buttons['saveConfig'] = tkinter.Button(self.buttonFrame, text='Save configuration',
            command=self.saveConfig)
        self.buttons['saveConfig'].bind('<Return>', self.saveConfig)

        self.buttons['rotateImage90'] = tkinter.Button(self.buttonFrame, text='Rotate image',
            command=self.rotateImage90)
        self.buttons['rotateImage90'].bind('<Return>', self.rotateImage90)

        for idx in range(4):
            self.buttons[f'activateSheet{idx}'] = tkinter.Button(self.buttonFrame, text=f'Edit sheet {idx}',
                command=functools.partial(self.setActiveSheet, idx))
            self.buttons[f'activateSheet{idx}'].bind('<Return>', functools.partial(self.setActiveSheet, idx))

        self.buttons['splitSheets'] = tkinter.Button(self.buttonFrame, text='Split sheets',
            command=self.splitSheets)
        self.buttons['splitSheets'].bind('<Return>', self.splitSheets)

        self.buttons['recognizeTags'] = tkinter.Button(self.buttonFrame, text='Recognize tags',
            command=self.recognizeTags)
        self.buttons['recognizeTags'].bind('<Return>', self.recognizeTags)
        if self.readyForTagRecognition:
            self.buttons['recognizeTags'].config(state='normal')
        else:
            self.buttons['recognizeTags'].config(state='disabled')

        y = 60
        for b in self.buttons.values():
            b.place(relx=.5, y=y, anchor="center",
                    width=.8*self.buttonFrameWidth)
            b.update()
            y += b.winfo_height()

    def loadConfigAndResetGUI(self):
        self.loadConfig()
        self.populateRoot()

    def loadConfig(self):
        self.rotationAngle = self.db.config.getint('tagtrail_ocr', 'rotationAngle')
        self.sheetCoordinates[0] = list(map(float,
            self.db.config.getcsvlist('tagtrail_ocr', 'sheet0_coordinates')))
        self.sheetCoordinates[1] = list(map(float,
            self.db.config.getcsvlist('tagtrail_ocr', 'sheet1_coordinates')))
        self.sheetCoordinates[2] = list(map(float,
            self.db.config.getcsvlist('tagtrail_ocr', 'sheet2_coordinates')))
        self.sheetCoordinates[3] = list(map(float,
            self.db.config.getcsvlist('tagtrail_ocr', 'sheet3_coordinates')))

    def saveConfig(self):
        self.db.config.set('tagtrail_ocr', 'rotationAngle', str(self.rotationAngle))
        self.db.config.set('tagtrail_ocr', 'sheet0_coordinates', str(', '.join(map(str, self.sheetCoordinates[0]))))
        self.db.config.set('tagtrail_ocr', 'sheet1_coordinates', str(', '.join(map(str, self.sheetCoordinates[1]))))
        self.db.config.set('tagtrail_ocr', 'sheet2_coordinates', str(', '.join(map(str, self.sheetCoordinates[2]))))
        self.db.config.set('tagtrail_ocr', 'sheet3_coordinates', str(', '.join(map(str, self.sheetCoordinates[3]))))
        self.db.writeConfig()

    def setActiveSheet(self, index):
        self.activeSheetIndex = index

    def onMouseDownOnScanCanvas(self, event):
        if self.activeSheetIndex is None:
            return

        if len(self.__selectedCorners) < 2:
            self.__selectedCorners.append([event.x, event.y])

        if len(self.__selectedCorners) == 2:
            # TODO same logic as in dialog
            self.root.update()
            canvasWidth = self.scanCanvas.winfo_width()
            canvasHeight = self.scanCanvas.winfo_height()
            self.sheetCoordinates[self.activeSheetIndex] = [
                    self.__selectedCorners[0][0] / canvasWidth,
                    self.__selectedCorners[0][1] / canvasHeight,
                    self.__selectedCorners[1][0] / canvasWidth,
                    self.__selectedCorners[1][1] / canvasHeight
                    ]
            self.__selectedCorners = []
            self.setActiveSheet(None)

        self.resetScanCanvas()

    def resetScanCanvas(self):
        self.scanCanvas.delete("all")
        self.scanCanvas.create_image(0,0, anchor=tkinter.NW, image=self.resizedImg)

        for corners in self.__selectedCorners:
            r = 2
            self.scanCanvas.create_oval(
                    corners[0]-r,
                    corners[1]-r,
                    corners[0]+r,
                    corners[1]+r,
                    outline = 'red')

        self.root.update()
        canvasWidth = self.scanCanvas.winfo_width()
        canvasHeight = self.scanCanvas.winfo_height()
        sheetColors = ['green', 'blue', 'red', 'orange']
        for sheetIndex, sheetCoords in enumerate(self.sheetCoordinates):
            if sheetIndex == self.activeSheetIndex:
                continue

            self.scanCanvas.create_rectangle(
                    sheetCoords[0] * canvasWidth,
                    sheetCoords[1] * canvasHeight,
                    sheetCoords[2] * canvasWidth,
                    sheetCoords[3] * canvasHeight,
                    outline = sheetColors[sheetIndex],
                    width = 2)

    def onMouseDownOnPreviewCanvas(self, event):
        assert(self.previewCanvas == event.widget)
        x = self.previewCanvas.canvasx(event.x)
        y = self.previewCanvas.canvasy(event.y)
        self.log.debug(f'clicked at {event.x}, {event.y} - ({x}, {y}) on canvas')

        row = int(y // self.previewRowHeight)
        col = int(x // self.previewColumnWidth)
        sheetRegionIdx = row*self.previewColumnCount + col
        self.log.debug(f'clicked on preview {sheetRegionIdx}, row={row}, col={col}')
        if len(self.model.sheetRegions) <= sheetRegionIdx:
            return

        sheetRegion = self.model.sheetRegions[sheetRegionIdx]
        dialog = SplitSheetDialog(self.root, sheetRegion.unprocessedImg, self.model)
        if dialog.isEmpty:
            sheetRegion.processedImg = self.model.crossedOutCopy(sheetRegion.unprocessedImg)
            sheetRegion.isEmpty = True
            self.resetPreviewCanvas(scrollToBottom=False)
        elif dialog.outputImg is not None:
            helpers.recreateDir(sheetRegion.tmpDir)
            sheetRegion.processedImg = dialog.outputImg
            sheetRegion.isEmpty = False
            self.resetPreviewCanvas(scrollToBottom=False)

    def onMouseWheelPreviewCanvas(self, event):
        increment = 0
        # respond to Linux or Windows wheel event
        if event.num == 5 or event.delta < 0:
            increment = 1
        if event.num == 4 or event.delta > 0:
            increment = -1
        self.previewCanvas.yview_scroll(increment, "units")

    def splitSheets(self):
        self.readyForTagRecognition = False

        self.setupProgressIndicator('Splitting progress')
        self.model.prepareScanSplitting()
        for scanFileIndex, scanFilename in enumerate(self.model.scanFilenames):
            if self.abortingProcess:
                break
            self.updateProgressIndicator(scanFileIndex /
                    len(self.model.scanFilenames) * 100)

            self.model.splitScan(scanFilename, self.sheetCoordinates,
                    self.rotationAngle)
            self.resetPreviewCanvas(scrollToBottom=True)

        self.destroyProgressIndicator()

        if not self.previewImages:
            messagebox.showwarning('Nothing to preview',
                f'All split sheets were found empty - probably sheet transformation settings are bad')
            return

        if not self.abortingProcess:
            self.readyForTagRecognition = True
            self.populateRoot()

    def resetPreviewCanvas(self, scrollToBottom=False):
        self.previewCanvas.delete('all')
        self.previewImages = []

        for sheetRegion in self.model.sheetRegions:
            height, width, _ = sheetRegion.processedImg.shape
            resizeRatio = self.previewCanvas.winfo_width() / (self.previewColumnCount * width)
            resizedWidth, resizedHeight = int(width * resizeRatio), int(height * resizeRatio)
            resizedImg = cv.resize(sheetRegion.processedImg, (resizedWidth, resizedHeight), Image.BILINEAR)
            resizedImg = ImageTk.PhotoImage(Image.fromarray(resizedImg))
            # Note: it is necessary to store the image locally for tkinter to show it
            self.previewImages.append(resizedImg)

            row = (len(self.previewImages)-1) // self.previewColumnCount
            col = (len(self.previewImages)-1) % self.previewColumnCount
            self.previewCanvas.create_image(col*self.previewColumnWidth, row*self.previewRowHeight, anchor=tkinter.NW, image=resizedImg)
            self.previewCanvas.create_rectangle(
                    col*self.previewColumnWidth,
                    row*self.previewRowHeight,
                    (col+1)*self.previewColumnWidth,
                    (row+1)*self.previewRowHeight
                    )

        self.previewCanvas.configure(scrollregion=self.previewCanvas.bbox("all"))
        if scrollToBottom:
            self.previewCanvas.yview_moveto('1.0')
        self.root.update()

    def recognizeTags(self):
        if (self.model.sheetRegions == [] or
                self.readyForTagRecognition == False):
            messagebox.showerror('Sheets missing', 'Unable to recognize tags - input images need to be split first')
            return

        self.setupProgressIndicator()
        with self.model:
            for idx, sheet in enumerate(self.model.sheetRegions):
                if self.abortingProcess:
                    break
                self.updateProgressIndicator(idx / len(self.model.sheetRegions)
                        * 100, sheet.name)
                self.model.recognizeTags(sheet)

        self.destroyProgressIndicator()

        if self.abortingProcess:
            return

        if messagebox.askyesno('OCR completed',
                'tagtrail_ocr is done - exit now?'):
            self.root.destroy()

def main(accountingDir, tmpDir, writeDebugImages):
    outputDir = f'{accountingDir}2_taggedProductSheets/'
    helpers.recreateDir(tmpDir)
    db = Database(f'{accountingDir}0_input/')
    for (parentDir, dirNames, fileNames) in os.walk(f'{accountingDir}0_input/scans/'):
        model = Model(tmpDir, parentDir, outputDir, fileNames, db, writeDebugImages)
        gui = GUI(model, db)
        if model.sheetRegions == [] or gui.abortingProcess:
            break

        gui.log.info('')
        gui.log.info(f'successfully processed {len(fileNames)} files')
        gui.log.info(f'the following files generated less than {ScanSplitter.numberOfSheets} sheets')
        for f in model.partiallyFilledFiles:
            gui.log.info(f)
        break

if __name__== "__main__":
    parser = argparse.ArgumentParser(
        description='Recognize tags on all input scans, storing them as CSV files')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    parser.add_argument('--tmpDir', dest='tmpDir', default='data/tmp/',
            help='Directory to put temporary files in')
    parser.add_argument('--writeDebugImages', dest='writeDebugImages', action='store_true')
    args = parser.parse_args()
    main(args.accountingDir, args.tmpDir, args.writeDebugImages)
