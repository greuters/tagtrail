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
import tesserocr
import PIL
import os
import math
import Levenshtein
import slugify
import tkinter
import logging
from tkinter import ttk
from tkinter import messagebox
from tkinter.simpledialog import Dialog
import imutils
import functools
from PIL import ImageTk,Image
from abc import ABC, abstractmethod
import sys

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

    :param name: name of the processor, used to identify debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
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
                 sheetRegion0 = (0, 0, .5, .5),
                 sheetRegion1 = (.5, 0, 1, .5),
                 sheetRegion2 = (0, .5, .5, 1),
                 sheetRegion3 = (.5, .5, 1, 1),
                 ):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.logger = logging.getLogger('tagtrail.tagtrail_ocr.ScanSplitter')
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
            self.logger.debug(f'assume empty sheet (no sheet contour found)')
            return None

        # biggest contour is assumed to be the sheet
        sheetContour = cnts[0]
        cntX, cntY, cntW, cntH = cv.boundingRect(sheetContour)

        if cntW * cntH < self.minSheetSize:
            self.logger.debug(f'assume empty sheet (sheet contour too small)')
            return None

        sheet = np.copy(sheetImg[cntY:cntY+cntH, cntX:cntX+cntW])
        self.__sheetImgs.append(sheet)

        frameFinder = ContourBasedFrameFinder(f'{self.name}_sheet{sheetRegionIdx}_5_frameFinder',
                self.tmpDir, self.writeDebugImages)
        frameContour = frameFinder.process(sheet)
        if frameContour is None:
            findMarginsByLines = LineBasedFrameFinder(
                    f'{self.name}_sheet{sheetRegionIdx}_6_frameFinderByLines',
                    self.tmpDir, self.writeDebugImages,
                    cropMargin = 40)
            frameContour = findMarginsByLines.process(sheet)

        if frameContour is None:
            self.logger.debug(f'assume empty sheet (no frame contour found)')
            return None

        normalizer = SheetNormalizer(
                f'{self.name}_sheet{sheetRegionIdx}_7_normalizer',
                self.tmpDir, self.writeDebugImages)
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

    :param name: name of the processor, used to identify debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False,
                 ):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.logger = logging.getLogger(
                'tagtrail.tagtrail_ocr.ContourBasedFrameFinder')

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
            self.logger.debug(f'no frame contour found')
            return None

        imgH, imgW = thresholdImg.shape
        _, _, cntW, cntH = cv.boundingRect(approxFrameContour)
        fillRatio = (cntW * cntH) / (imgW * imgH)
        if fillRatio < .5:
            self.logger.debug(f'frame contour not filled enough')
            self.logger.debug(f'imgH, imgW = {imgH}, {imgW}')
            self.logger.debug(f'cntH, cntW = {cntH}, {cntW}')
            self.logger.debug(f'fillRatio = {fillRatio}')
            return None

        return approxFrameContour.reshape(4, 2)

class LineBasedFrameFinder():
    """
    A processor that takes an image which presumably contains a ProductSheet printed on white
    paper as input and identifies the contour of the bold frame on it.

    :class:`LineBasedFrameFinder` finds frames even if they are not complete,
    but gets confused by sheet boundaries if the sheet is not well detected.

    :param name: name of the processor, used to identify debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    :param minLineLength: Minimum length of line. Line segments shorter than
        this are rejected
    :type minLineLength: int
    :param cropMargin: LineBasedFrameFinder is easily confused by sheet
        borders, thus it can help to crop sheet by cropMargin on all sides before
        processing
    :type cropMargin: int
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False,
                 minLineLength = 800,
                 cropMargin = 0):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.logger = logging.getLogger(
                'tagtrail.tagtrail_ocr.LineBasedFrameFinder')
        self.pixelAccuracy = 1
        self.rotationAccuracy = np.pi/180
        self.minLineLength = minLineLength
        self.cropMargin = cropMargin

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
        inputImgH, inputImgW, _ = inputImg.shape
        croppedImg = np.copy(inputImg[
            self.cropMargin:inputImgH-self.cropMargin,
            self.cropMargin:inputImgW-self.cropMargin])
        grayImg = cv.cvtColor(croppedImg,cv.COLOR_BGR2GRAY)
        blurredImg = cv.GaussianBlur(grayImg, (7, 7), 3)
        thresholdImg = cv.adaptiveThreshold(blurredImg, 255,
                cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY, 11, 2)
        thresholdImg = cv.bitwise_not(thresholdImg)

        houghLines = cv.HoughLines(thresholdImg, self.pixelAccuracy,
                self.rotationAccuracy, self.minLineLength)
        lineMaskImg = np.zeros(thresholdImg.shape, dtype="uint8")
        for line in houghLines:
            rho,theta = line[0]
            a = np.cos(theta)
            b = np.sin(theta)
            x0 = a*rho
            y0 = b*rho
            x1 = int(x0 + 3000*(-b))
            y1 = int(y0 + 3000*(a))
            x2 = int(x0 - 3000*(-b))
            y2 = int(y0 - 3000*(a))
            cv.line(lineMaskImg, (x1,y1), (x2,y2), 255, 2)

        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_0_gray.jpg', grayImg)
            cv.imwrite(f'{self.__prefix}_1_blurred.jpg', blurredImg)
            cv.imwrite(f'{self.__prefix}_2_threshold.jpg', thresholdImg)
            cv.imwrite(f'{self.__prefix}_3_lines.jpg', lineMaskImg)

        harrisDstImg = cv.cornerHarris(lineMaskImg, 2, 3, 0.04)
        corners = np.argwhere(harrisDstImg.transpose() >
                0.5*harrisDstImg.max())
        if corners is None:
            self.logger.debug('Failed to find corners, not cropping image')
            return None

        frameImg = np.copy(croppedImg)
        for corner in corners:
            cv.circle(frameImg, (corner[0], corner[1]), 5, (0, 0, 255), 5)

        hull = cv.convexHull(np.array(corners))
        frameContour = cv.approxPolyDP(hull, 200, True)
        frameContour = np.array([[x[0][0], x[0][1]] for x in frameContour])
        if self.writeDebugImages:
            cv.drawContours(frameImg, [frameContour], 0, (0, 0, 255), 4)

        if len(frameContour) != 4:
            boundingRect = cv.minAreaRect(np.array(corners))
            frameContour = np.int0(cv.boxPoints(boundingRect))
            if self.writeDebugImages:
                cv.drawContours(frameImg, [frameContour], 0, (0, 255, 0), 4)

        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_4_frame.jpg', frameImg)

        imgH, imgW, _ = frameImg.shape
        frameContourArea = cv.contourArea(frameContour)
        fillRatio = frameContourArea / (imgW * imgH)
        if fillRatio < .5:
            self.logger.debug(f'frame contour not filled enough')
            self.logger.debug(f'imgH, imgW = {imgH}, {imgW}')
            self.logger.debug(f'frameContourArea = {frameContourArea}')
            self.logger.debug(f'fillRatio = {fillRatio}')
            return None

        return np.array([[x+self.cropMargin, y+self.cropMargin] for (x, y) in
            frameContour])

class SheetNormalizer():
    """
    A processor that takes an image and the contour of the frame of a ProductSheet on it,
    transforms it back to represent the original ProductSheet as closely as
    possible.

    :param name: name of the processor, used to identify debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False
                 ):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.logger = logging.getLogger('tagtrail.tagtrail_ocr.SheetNormalizer')

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

        # convert frame metrics to pixels
        (frameP0, frameP1) = ProductSheet.getSheetFramePts()
        frameWidth, frameHeight = np.subtract(frameP1, frameP0)
        (leftMargin, topMargin) = ProductSheet.pointFromMM(
                ProductSheet.leftSheetFrame, ProductSheet.topSheetFrame)
        (rightMargin, bottomMargin) = ProductSheet.pointFromMM(
                ProductSheet.rightSheetFrame, ProductSheet.bottomSheetFrame)

        resizedImg = cv.resize(rectifiedImg, (frameWidth, frameHeight))
        outputImg = cv.copyMakeBorder(resizedImg,
                topMargin,
                bottomMargin,
                leftMargin,
                rightMargin,
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
    """
    minNumMatchingTextsForIdentification = 8

    def __init__(self,
            name,
            inputSheetsDir,
            tmpDir,
            db,
            tesseractApi,
            writeDebugImages = False,
            searchMarginSize = 25,
            cornerBorderSize = 5,
            rotationBorderSize = 20,
            minPlausibleBoxSize = 1000,
            minComponentArea = 100,
            minAspectRatio = .2,
            minFillRatio = .3,
            confidenceThreshold = 0.5
            ):
        """
        :param name: name of the processor, used to identify debug images
        :type name: str
        :param inputSheetsDir: directory where previous versions of the scanned product
            sheets are stored
        :type inputSheetsDir: str
        :param tmpDir: directory to write debug images to
        :type tmpDir: str
        :param db: database with possible box values and configurations
        :type db: class: `database.Database`
        :param tesseractApi: API interface to tesseract
        :type tesseractApi: class `tesserocr.PyTessBaseAPI`
        :param writeDebugImages: `True` if debug images shold be written. This
            slows down processing significantly.
        :param writeDebugImages: bool
        :param searchMarginSize: margin by which each box image is extended to look
            for its actual corners
        :type searchMarginSize: int
        :param cornerBorderSize: Size of the border of a box that is discarded
            when identifying relevant contours in a box. After the actual
            corners of a box are identified, their bounding rectangle is shrunk
            by cornerBorderSize before searching contours relevant for OCR.
        :type cornerBorderSize: int
        :param rotationBorderSize: Size of the border around a box that is
            additionally used for rotation. After the actual corners of a box
            are identified and the relevant contours have been found, the min
            enclosing rectangle of the contours is found and rotated to be
            horizontal. To avoid missing pixels during rotation, a region
            rotationBorderSize larger than the box is used for rotation.
        :type rotationBorderSize: int
        :param minPlausibleBoxSize: Minimal size of a box to be considered
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
        :type minAspectRatio: float
        :param minFillRatio: Minimal fill ratio of the final bounding rect
            considered for OCR
        :type minFillRatio: float
        :param confidenceThreshold: Minimal confidence needed to color the
            recognized box text as 'safely recognized' in the debug output image.
            For confidence calculation, check `self.__findClosestString`
        :type confidenceThreshold: float
        """

        self.name = name
        self.inputSheetsDir = inputSheetsDir
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.logger = logging.getLogger('tagtrail.tagtrail_ocr.TagRecognizer')
        self.searchMarginSize = searchMarginSize
        self.cornerBorderSize = cornerBorderSize
        self.rotationBorderSize = rotationBorderSize
        self.minPlausibleBoxSize = minPlausibleBoxSize
        self.minComponentArea = minComponentArea
        self.minAspectRatio = minAspectRatio
        self.minFillRatio = minFillRatio
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
                sheetNumberString.format(sheetNumber=str(n))
                for n in range(1, maxNumSheets+1)]
        self.logger.debug(f'sheetNumberCandidates={list(self.__sheetNumberCandidates)}')

        self.__productNameCandidates = [p.description
                for p in self.__db.products.values()]
        self.logger.debug(f'productNameCandidates={list(self.__productNameCandidates)}')

        self.__unitCandidates = [p.amountAndUnit
                for p in self.__db.products.values()]
        self.logger.debug(f'unitCandidates={list(self.__unitCandidates)}')

        self.currency = self.__db.config.get('general', 'currency')
        self.__priceCandidates = [
                helpers.formatPrice(p.grossSalesPrice(), self.currency)
                for p in self.__db.products.values()]
        self.logger.debug(f'priceCandidates={list(self.__priceCandidates)}')

        self.__memberIdCandidates = [m.id for m in self.__db.members.values()]
        self.logger.debug(f'memberIdCandidates={list(self.__memberIdCandidates)}')

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

    def filename(self):
        """
        Recognized file name. If recognition failed or is not yet done, a
        fallback is returned.
        """
        return self.__sheet.filename

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
            if box.name == 'nameBox':
                name, confidence = self.__recognizeBoxText(box,
                        self.__productNameCandidates)
                if name == '' or confidence < 0.5:
                    box.text, box.confidence = fallbackSheetName, 0
                else:
                    box.text, box.confidence = name, confidence
            elif box.name == 'unitBox':
                box.text, box.confidence = self.__recognizeBoxText(box,
                        self.__unitCandidates)
                if box.text == '':
                    box.confidence = 0
            elif box.name == 'priceBox':
                box.text, box.confidence = self.__recognizeBoxText(box,
                        self.__priceCandidates)
                if box.text == '':
                    box.confidence = 0
            elif box.name == "sheetNumberBox":
                sheetNumber, confidence = self.__recognizeBoxText(box,
                        self.__sheetNumberCandidates)
                if sheetNumber == '' or confidence < 1:
                    box.text, box.confidence = str(fallbackSheetNumber), 0
                else:
                    box.text, box.confidence = sheetNumber, confidence
            elif box.name.find('dataBox') != -1:
                box.text, box.confidence = self.__recognizeBoxText(box,
                        self.__memberIdCandidates)
            else:
                box.text, box.confidence = ("", 1.0)

        # set sheetNumber if identified product only has one active sheet
        # this is a heuristic saving a lot of work in practice, as sheetNumbers
        # are notoriously difficult to OCR (only one identifying character) and
        # there are typically many products with only one sheet
        if self.__sheet.boxByName('nameBox').confidence != 0:
            productId = self.__sheet.productId()
            sheetNumberBox = self.__sheet.boxByName('sheetNumberBox')
            sheetFilenames = [
                    f for f in os.listdir(f'{self.inputSheetsDir}active/')
                    if ProductSheet.productId_from_filename(f) == productId]
            if len(sheetFilenames) == 1:
                self.logger.info('inferred sheetNumber from productId '
                        f'{productId} -> {sheetNumberBox.text}')
                sheetNumberBox.text = ProductSheet.sheetNumber_from_filename(
                        sheetFilenames[0])

        self.__identifySheet()

        for box in self.__sheet.boxes():
            if box.confidence < self.confidenceThreshold:
                box.bgColor = (0, 0, 80)

        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_1_outputImage.jpg', self.__sheet.createImg())

    def __identifySheet(self):
        """
        Try to identify the sheet

        Automatic identification is rather conservative, a sheet is considered
        correctly identified if all of the following are true:
            * nameBox has a recognized text, allowing to identify the product
              and compare tags to the corresponding input sheets (several
              sheets with different sheet numbers are compared)
            * for one of the products input sheets, all confident tags on the
              sheet match the corresponding non-empty tags of the input sheet
            * at least `self.minNumMatchingTextsForIdentification` could be
              compared between the sheet and the input sheet

        If identification is successful, confidence of nameBox and
        sheetNumberBox is set to 1 and sheetNumberBox.text is set to the
        correct number.

        If not, confidence of nameBox and sheetNumberBox are set to 0.
        """
        nameBox = self.__sheet.boxByName('nameBox')
        sheetNumberBox = self.__sheet.boxByName('sheetNumberBox')
        if nameBox.confidence == 0:
            sheetNumberBox.confidence = 0

        for (root, _, filenames) in itertools.chain(
                os.walk(f'{self.inputSheetsDir}active/'),
                os.walk(f'{self.inputSheetsDir}inactive/')):
            for filename in filenames:
                if (self.__sheet.productId() !=
                        ProductSheet.productId_from_filename(filename)):
                    continue
                if self.__isInputSheet(f'{root}{filename}'):
                    nameBox.confidence = 1
                    sheetNumberBox.text = ProductSheet.sheetNumber_from_filename(filename)
                    sheetNumberBox.confidence = 1
                    return

        nameBox.confidence = 0
        sheetNumberBox.confidence = 0

    def __isInputSheet(self, inputSheetPath):
        """
        Check if input sheet matches self.__sheet

        :param inputSheetPath: path to load the input sheet to compare from
        :type inputSheetPath: str
        :return: True if the input sheet matches self.__sheet, False otherwise
        :rtype: bool
        :raises ValueError: if the given input sheet is not fully sanitized
        """
        self.logger.debug(f'test if {inputSheetPath} matches this sheet')
        inputSheet = ProductSheet()
        inputSheet.load(inputSheetPath)

        unconfidentBoxes = [box for box in inputSheet.boxes() if box.confidence != 1]
        if unconfidentBoxes != []:
            raise ValueError(f'{inputSheetPath} has unconfident boxes: '
                    f'{unconfidentBoxes}')

        numTextsCompared = 0
        for box in self.__sheet.boxes():
            if box.confidence != 1:
                continue

            inputBox = inputSheet.boxByName(box.name)
            if inputBox.text != '':
                numTextsCompared += 1
                if inputBox.text != box.text:
                    self.logger.debug(f'non-matching tag in box {box.name} '
                            f'found: {inputBox.text} != {box.text}')
                    return False

        if self.minNumMatchingTextsForIdentification <= numTextsCompared:
            self.logger.debug(f'match found: {inputSheetPath}')
            return True
        else:
            self.logger.debug('not enough matching tags compared to '
                f'confirm match ({numTextsCompared})')
            return False

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
            self.logger.debug(f'stats[label, cv.CC_STAT_AREA]={stats[label, cv.CC_STAT_AREA]}')
            if stats[label, cv.CC_STAT_AREA] < self.minComponentArea:
                self.logger.debug('component removed, too small')
                continue

            if maxComponentArea < stats[label, cv.CC_STAT_AREA]:
                self.logger.debug('component removed, too big')
                continue

            componentWidth = stats[label, cv.CC_STAT_WIDTH]
            componentHeight = stats[label, cv.CC_STAT_HEIGHT]
            aspectRatio = (min(componentWidth, componentHeight) /
                    max(componentWidth, componentHeight))
            self.logger.debug(f'stats[label, cv.CC_STAT_WIDTH]={componentWidth}')
            self.logger.debug(f'stats[label, cv.CC_STAT_HEIGHT]={componentHeight}')
            self.logger.debug(f'aspectRatio={aspectRatio}')
            if aspectRatio < self.minAspectRatio:
                continue

            mask = np.where(labeledImg == label, np.uint8(255.0),
                    np.uint8(0.0))
            x, y, w, h = cv.boundingRect(mask)
            boundingRectArea = w * h
            if maxComponentArea < boundingRectArea:
                self.logger.debug(f'component removed, boundingRect too big {w*h}')
                continue

            boundingRectFillFactor = stats[label, cv.CC_STAT_AREA] / boundingRectArea
            if boundingRectFillFactor < 0.35:
                self.logger.debug(f'boundingRectFillFactor = {boundingRectFillFactor}')
                self.logger.debug('component removed, too sparsly filled')
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
            cv.imwrite(f'{self.__prefix}_{box.name}_08_dilatedImg.jpg', dilatedImg)

        # find contours in the thresholded cell
        cnts = cv.findContours(dilatedImg.copy(), cv.RETR_EXTERNAL,
                cv.CHAIN_APPROX_SIMPLE)
        cnts = imutils.grab_contours(cnts)
        # if no contours were found than this is an empty cell
        if len(cnts) == 0:
            box.bgColor = (255, 0, 0)
            return ("", 1.0)

        # otherwise, take contours (from biggest to smallest) until the
        # percentage of white pixels in the common bounding rect area is
        # getting too low
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
                if( area / (newCommonArea - commonArea + 1) > self.minFillRatio):
                    commonBoundingRect = newCommonBoundingRect
                    cv.drawContours(maskImg, [cnt], -1, 255, -1)
        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_{box.name}_09_maskImg.jpg', maskImg)

        centerX = commonBoundingRect[0] + commonBoundingRect[2] / 2
        centerY = commonBoundingRect[1] + commonBoundingRect[3] / 2
        h, w = maskImg.shape
        minBorderDist = 20
        if centerX < minBorderDist or w - minBorderDist < centerX or centerY < minBorderDist or h - minBorderDist < centerY:
            self.logger.debug(f'{box.name} centerX = {centerX}, centerY = {centerY}')
            self.logger.debug(f'{box.name} too close to border, h = {h}, w = {w}')
            box.bgColor = (255, 0, 0)
            return ("", 1.0)

        # compute the percentage of masked pixels relative to the total
        # area of the image
        (h, w) = maskImg.shape
        percentFilled = cv.countNonZero(maskImg) / float(w * h)
        # if less than 3% of the mask is filled then we are looking at
        # noise and can safely ignore the contour
        if percentFilled < 0.03:
            self.logger.debug(f'not filled enough, percentFilled = {percentFilled}')
            box.bgColor = (255, 0, 0)
            return ("", 1.0)

        # use a bigger region around the tag for rotation, to avoid cutting
        # corners when rotating
        p = RotateTag(f'_{box.name}_09_rotation', self.__prefix,
                writeDebugImages = self.writeDebugImages)
        rotationInputImg = self.__inputImg[
                y0-self.rotationBorderSize:y1+self.rotationBorderSize,
                x0-self.rotationBorderSize:x1+self.rotationBorderSize]
        rotationInputMask = cv.copyMakeBorder(maskImg, self.rotationBorderSize,
                self.rotationBorderSize, self.rotationBorderSize, self.rotationBorderSize,
                cv.BORDER_CONSTANT, value=(0, 0, 0))
        rotatedImg = p.process(rotationInputImg, rotationInputMask)

        # blend ocrImg with thresholded version
        grayImg = cv.cvtColor(rotatedImg, cv.COLOR_BGR2GRAY)
        _, thresholdImg = cv.threshold(grayImg,0,255,cv.THRESH_OTSU)
        thresholdImg = cv.cvtColor(thresholdImg, cv.COLOR_GRAY2BGR)
        ocrImg = cv.addWeighted(rotatedImg, .95, thresholdImg, .05, 0)

        if self.writeDebugImages:
            cv.imwrite(f'{self.__prefix}_{box.name}_10_ocrImage.jpg', ocrImg)

        self.tesseractApi.SetImage(Image.fromarray(ocrImg))
        ocrText = self.tesseractApi.GetUTF8Text().strip()

        confidence, text = self.__findClosestString(ocrText, candidateTexts)
        self.logger.info(f"(ocrText, confidence, text) = ({ocrText}, {confidence}, {text})")
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
        assert(min(cornerImg.shape) > 1)

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
                [extendedX0 + cornerX0 + self.cornerBorderSize,
                   extendedY0 + cornerY0 + self.cornerBorderSize],
                [extendedX0 + cornerX1 - self.cornerBorderSize,
                    extendedY0 + cornerY1 - self.cornerBorderSize]
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
        self.logger.debug(f"findClosestString: searchString={searchString}")
        self.logger.debug(f"findClosestString: candidateStrings={candidateStrings}")
        dists = list(map(lambda x: Levenshtein.distance(x,
            searchString.upper()), [c.upper() for c in candidateStrings]))
        self.logger.debug(f"dists={dists}")
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
        Store the recognized sheet as f'{outputDir}{self.filename()}

        :param outputDir: directory to store the csv file to
        :type outputDir: str
        :raises ValueError: if the file already exists and would be overwritten
        """
        if os.path.exists(f'{outputDir}{self.filename()}'):
            raise ValueError(
                f'{outputDir}{self.filename()} already exists')
        self.__sheet.store(outputDir)
        self.logger.info('')

class RotateTag():
    """
    A processor that takes the original image of a tag and a cleaned mask of
    the characters on the tag, identifies the bounding rectangle of all
    contours on the mask and returns a copy of the original image cropped to
    the bounding rectangle of the contours and rotated to be horizontal.

    :param name: name of the processor, used to identify logs and debug images
    :type name: str
    :param tmpDir: directory to write debug images to
    :type tmpDir: str
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    """
    def __init__(self,
                 name,
                 tmpDir = 'data/tmp/',
                 writeDebugImages = False):
        self.name = name
        self.tmpDir = tmpDir
        self.writeDebugImages = writeDebugImages
        self.logger = logging.getLogger('tagtrail.tagtrail_ocr.RotateTag')

    def process(self, originalImg, maskImg):
        """
        Crop and rotate the tag contours

        :param originalImg: original scanned image of the region around the tag
        :type originalImg: BGR image
        :param maskImg: masked copy of originalImg where all relevant contours
            are in white
        :type maskImg: black/white image
        :return: warped sub-image of the originalImg, cropped to the bounding
            rectangle of the contours in maskImg and rotated to be horizontal
        :rtype: BGR image
        """
        # find minAreaRect of joint contours
        contours, _ = cv.findContours(maskImg, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        joinedContour = np.vstack(contours)
        minAreaRect = cv.minAreaRect(joinedContour)
        center, (minAreaRectWidth, minAreaRectHeight), rotationAngle = minAreaRect
        minAreaRectWidth *= 1.1
        minAreaRectHeight *= 1.1

        # extract the rotated minAreaRect from the original
        if minAreaRectWidth < minAreaRectHeight:
            rotationAngle -= 90
            minAreaRectWidth, minAreaRectHeight = minAreaRectHeight, minAreaRectWidth
        rotationMatrix = cv.getRotationMatrix2D(center, rotationAngle, 1.0)

        originalImgHeight, originalImgWidth, _ = originalImg.shape
        rotatedImg = cv.warpAffine(originalImg, rotationMatrix,
                (originalImgWidth, originalImgHeight), flags=cv.INTER_CUBIC,
                borderMode=cv.BORDER_REPLICATE)
        outputImg = cv.getRectSubPix(rotatedImg,
                (int(minAreaRectWidth), int(minAreaRectHeight)), center)

        if self.writeDebugImages:
            minAreaImg = cv.cvtColor(np.copy(maskImg), cv.COLOR_GRAY2BGR)
            cv.drawContours(minAreaImg,[np.int0(cv.boxPoints(minAreaRect))],0,(0,0,255),2)
            minAreaImgHeight, minAreaImgWidth, _ = minAreaImg.shape
            minAreaRotatedImg = cv.warpAffine(minAreaImg, rotationMatrix,
                    (minAreaImgWidth, minAreaImgHeight), flags=cv.INTER_CUBIC,
                    borderMode=cv.BORDER_REPLICATE)

            cv.imwrite(f'{self.tmpDir}{self.name}_0_input.jpg', originalImg)
            cv.imwrite(f'{self.tmpDir}{self.name}_1_minArea.jpg', minAreaImg)
            cv.imwrite(f'{self.tmpDir}{self.name}_2_minAreaRotated.jpg', minAreaRotatedImg)
            cv.imwrite(f'{self.tmpDir}{self.name}_3_output.jpg', outputImg)

        return outputImg

class Corner:
    """
    A corner selected on screen
    """
    def __init__(self, x, y):
        self.x = x
        self.y = y

class SplitSheetDialog(Dialog):
    """
    A dialog to correct wrongly split sheets before OCR.
    """

    initialScreenPercentage = 0.75

    def __init__(self,
            root,
            inputImg,
            model):
        self.inputImg = inputImg
        self._resizedInputImg = None
        self.model = model
        self.logger = logging.getLogger('tagtrail.tagtrail_ocr.SplitSheetDialog')
        self.outputImg = None
        self._previewOutputImg = None
        self.isEmpty = False
        self._selectedCorners = []
        self.selectionMode = 'rectangle'
        self._templateImg = ProductSheet().createImg()
        super().__init__(root)

    @property
    def selectionMode(self):
        """
        Mode to select image, one of ('rectangle', 'corners')

        'rectangle' mode lets the user select the upper left and lower right
        corners of an axis-aligned rectangle, which is then processed by
        :class:`LineBasedFrameFinder` before normalization.

        'corners' mode lets the user directly select all four corners of the
        output image, which is then normalized

        Setting the mode clears all selected corners.
        """
        return self._selectionMode

    @selectionMode.setter
    def selectionMode(self, mode):
        if not mode in ('rectangle', 'corners'):
            raise ValueError("mode must be one of ('rectangle', 'corners')")
        self._selectionMode = mode
        self._selectedCorners = []

    def switchSelectionMode(self):
        if self.selectionMode == 'rectangle':
            self.selectionMode = 'corners'
        else:
            self.selectionMode = 'rectangle'

    def body(self, master):
        self.width = master.winfo_screenwidth() * self.initialScreenPercentage
        self.height = master.winfo_screenheight() * self.initialScreenPercentage
        o_h, o_w, _ = self.inputImg.shape
        aspectRatio = min(self.height / o_h, self.width / 2 / o_w)
        resizedImgHeight, resizedImgWidth = int(o_h * aspectRatio), int(o_w * aspectRatio)
        resizedImg = cv.resize(self.inputImg, (resizedImgWidth, resizedImgHeight), Image.BILINEAR)
        self._resizedInputImg = ImageTk.PhotoImage(Image.fromarray(resizedImg))
        self.logger.debug(f'resizedImgWidth, resizedImgHeight = {resizedImgWidth}, {resizedImgHeight}')

        self.inputCanvas = tkinter.Canvas(master,
               width=resizedImgWidth,
               height=resizedImgHeight)
        self.inputCanvas.bind("<Button-1>", self.onMouseDown)
        self.inputCanvas.bind("<Motion>", self.onMouseMotion)
        self.inputCanvas.pack(side = tkinter.LEFT)

        self.outputCanvas = tkinter.Canvas(master,
               width=resizedImgWidth,
               height=resizedImgHeight)
        self.outputCanvas.pack(side = tkinter.RIGHT)
        self.resetCanvas(None, None)

        return None

    def buttonbox(self):
        box = tkinter.Frame(self)

        w = tkinter.Button(box, text="OK", width=10, command=self.ok,
                default=tkinter.ACTIVE)
        w.pack(side=tkinter.LEFT, padx=5, pady=5)
        w = tkinter.Button(box, text="Empty sheet", width=10, command=self.markEmpty)
        w.pack(side=tkinter.LEFT, padx=5, pady=5)
        w = tkinter.Button(box, text="Switch selection mode", width=20,
                command=self.switchSelectionMode)
        w.pack(side=tkinter.LEFT, padx=5, pady=5)
        w = tkinter.Button(box, text="Cancel", width=10, command=self.cancel)
        w.pack(side=tkinter.LEFT, padx=5, pady=5)

        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

        box.pack()

    def markEmpty(self):
        self.isEmpty = True
        self.ok()

    def apply(self):
        self.computeOutputImg()

    def onMouseDown(self, event):
        maxNumCorners = 2 if self.selectionMode == 'rectangle' else 4
        if len(self._selectedCorners) < maxNumCorners:
            self._selectedCorners.append(Corner(event.x, event.y))
        else:
            self._selectedCorners = [Corner(event.x, event.y)]

        if len(self._selectedCorners) == maxNumCorners:
            self.computeOutputImg()
        else:
            self.outputImg = None
        self.resetCanvas(event.x, event.y)

    def onMouseMotion(self, event):
        self.resetCanvas(event.x, event.y)

    def resetCanvas(self, x, y):
        self.inputCanvas.delete("all")
        self.inputCanvas.create_image(0, 0, anchor=tkinter.NW, image=self._resizedInputImg)

        corners = []
        if self.selectionMode == 'rectangle':
            # define first two corners of diagonal
            if len(self._selectedCorners) == 1:
                corners.append(self._selectedCorners[0])
                corners.append(Corner(x, y))
            elif len(self._selectedCorners) == 2:
                corners.append(self._selectedCorners[0])
                corners.append(self._selectedCorners[1])
            # add corners on the other diagonal
            if corners != []:
                corners.insert(1, Corner(corners[0].x, corners[1].y))
                corners.append(Corner(corners[2].x, corners[0].y))
        elif self.selectionMode == 'corners':
            for c in self._selectedCorners:
                corners.append(c)
            if len(corners) < 4:
                corners.append(Corner(x, y))
        else:
            assert(False)


        linePts = list(itertools.chain(*[(c.x, c.y) for c in corners]))
        if len(corners) == 4:
            linePts.append(corners[0].x)
            linePts.append(corners[0].y)
        for c in corners:
            self.inputCanvas.create_oval(c.x-5, c.y-5, c.x+5, c.y+5)
        if 1 < len(corners):
            self.inputCanvas.create_line(linePts, fill = 'green', width = 4)

        self.outputCanvas.delete("all")
        if self._previewOutputImg is not None:
            self.outputCanvas.create_image(0, 0, anchor=tkinter.NW,
                    image=self._previewOutputImg)

    def computeOutputImg(self):
        self.update()
        canvasW = self.inputCanvas.winfo_width()
        canvasH = self.inputCanvas.winfo_height()
        imgH, imgW, _ = self.inputImg.shape
        normalizeX = lambda x: int(x / canvasW * imgW)
        normalizeY = lambda y: int(y / canvasH * imgH)

        frameContour = None
        img = None
        if self.selectionMode == 'rectangle' and len(self._selectedCorners) == 2:
            x0 = normalizeX(self._selectedCorners[0].x)
            y0 = normalizeY(self._selectedCorners[0].y)
            x1 = normalizeX(self._selectedCorners[1].x)
            y1 = normalizeY(self._selectedCorners[1].y)
            img = self.inputImg[y0:y1, x0:x1, :]

            frameContour = LineBasedFrameFinder(
                    'sheetDetector',
                    self.model.tmpDir,
                    self.model.writeDebugImages,
                    self.log
                    ).process(img)
        elif self.selectionMode == 'corners' and len(self._selectedCorners) == 4:
            frameContour = [
                    [normalizeX(c.x), normalizeY(c.y)]
                    for c in self._selectedCorners]
            img = self.inputImg

        if frameContour is None:
            self.logger.debug(f'no frame contour found, using cropped input img')
            self.outputImg = img.copy()
        else:
            self.outputImg = SheetNormalizer(
                    'normalizer',
                    self.model.tmpDir,
                    self.model.writeDebugImages,
                    self.log
                    ).process(img, np.array(frameContour))

        resizedTemplateImg = cv.cvtColor(cv.resize(self._templateImg, (canvasW,
            canvasH), Image.BILINEAR), cv.COLOR_RGB2GRAY)
        resizedOutputImg = cv.resize(self.outputImg, (canvasW,
            canvasH), Image.BILINEAR)
        maskedOutputImg = cv.bitwise_or(resizedOutputImg, resizedOutputImg,
                mask = resizedTemplateImg)

        self._previewOutputImg = ImageTk.PhotoImage(Image.fromarray(maskedOutputImg))

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
        self.recognizedName=None
        self.tmpDir=tmpDir
        self.unprocessedImg=unprocessedImg
        self.processedImg=processedImg
        self.isEmpty=isEmpty

class Model():
    """
    Model class exposing all functionality needed to process scanned
    ProductSheets and store their content as .csv files.

    :param rootDir: root directory for the accounting
    :type rootDir: str
    :param tmpDir: temporary directory to write debug images to
    :type tmpDir: str
    :param scanFilenames: list of filenames (input scans) to be processed
    :type scanFilenames: list of str
    :param clearOutputDir: if `True`, outputDir is recreated before processing
        new scans.
    :type clearOutputDir: bool
    :param writeDebugImages: `True` if debug images shold be written. This
        slows down processing significantly.
    :param writeDebugImages: bool
    """
    def __init__(self,
            rootDir,
            tmpDir,
            scanFilenames,
            clearOutputDir = True,
            writeDebugImages = False):
        self.rootDir = rootDir
        self.tmpDir = tmpDir
        self.scanDir = f'{rootDir}0_input/scans/'
        self.outputDir = f'{rootDir}2_taggedProductSheets/'
        self.scanFilenames = scanFilenames
        self.logger = logging.getLogger('tagtrail.tagtrail_ocr.Model')
        self.clearOutputDir = clearOutputDir
        self.fallbackSheetNumber = 0
        self.writeDebugImages = writeDebugImages
        self.db = Database(f'{rootDir}0_input/')
        self.sheetRegions = []
        self.partiallyFilledFiles = set()
        self.compressedImgWidth = self.db.config.getint('tagtrail_ocr',
                'output_img_width')
        self.compressedImgQuality = self.db.config.getint('tagtrail_ocr',
                'output_img_jpeg_quality')
        self.tesseractApi = None

    def __enter__(self):
        self.tesseractApi = tesserocr.PyTessBaseAPI(
               oem = tesserocr.OEM.LSTM_ONLY,
               psm = tesserocr.PSM.SINGLE_LINE)

    def __exit__(self, exc_type, exc_value, traceback):
        self.tesseractApi.End()
        self.tesseractApi = None

    def prepareScanSplitting(self):
        """
        Prepare to walk over self.scanFilenames and invoke self.splitScan with
        each of them.
        """
        self.sheetRegions = []

    def prepareTagRecognition(self):
        """
        Prepare to recognize tags on all split sheets again

        If self.clearOutputDir is `True`, any previously processed scans are
        discarded, and self.outputDir is emptied.
        """
        if self.clearOutputDir:
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
                sheetCoordinates[0],
                sheetCoordinates[1],
                sheetCoordinates[2],
                sheetCoordinates[3]
                )

        inputImg = cv.imread(self.scanDir + scanFilename)
        if inputImg is None:
            self.logger.warning(f'file {self.scanDir + scanFilename} could not be ' +
                    'opened as an image')
            return

        rotatedImg = imutils.rotate_bound(inputImg, rotationAngle)
        self.logger.info('')
        self.logger.info(f'Splitting scanned file: {scanFilename}')
        splitter.process(rotatedImg)
        for idx, splitImg in enumerate(splitter.outputSheetImgs):
            sheetName = f'{scanFilename}_sheet{idx}'
            self.logger.debug(f'sheetName = {sheetName}')
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
        recognizer = TagRecognizer("4_recognizeText",
                f'{self.rootDir}0_input/sheets/', sheetRegion.tmpDir, self.db,
                self.tesseractApi, writeDebugImages = self.writeDebugImages)
        recognizer.process(sheetRegion.processedImg, fallbackSheetName,
                self.fallbackSheetNumber)

        if os.path.exists(f'{self.outputDir}{recognizer.filename()}'):
            if self.clearOutputDir:
                self.logger.info('reset sheet to fallback name as '
                    f'{recognizer.filename()} already exists')
                recognizer.resetSheetToFallback(fallbackSheetName,
                        self.fallbackSheetNumber)
            else:
                self.logger.info(f'''overwriting {recognizer.filename()}, as it
                already exists and output directory has not been cleared due to
                --individualScan option''')
                os.remove(f'{self.outputDir}{recognizer.filename()}')

        recognizer.storeSheet(self.outputDir)
        self.fallbackSheetNumber += 1
        sheetRegion.recognizedName = recognizer.filename()

        cv.imwrite(f'{self.outputDir}{recognizer.filename()}_original_scan.jpg',
                imutils.resize(sheetRegion.unprocessedImg, width=self.compressedImgWidth),
                [int(cv.IMWRITE_JPEG_QUALITY), self.compressedImgQuality])
        cv.imwrite(f'{self.outputDir}{recognizer.filename()}_normalized_scan.jpg',
                imutils.resize(sheetRegion.processedImg, width=self.compressedImgWidth),
                [int(cv.IMWRITE_JPEG_QUALITY), self.compressedImgQuality])

class GUI(BaseGUI):
    previewColumnCount = 4
    buttonFrameWidth = 200
    previewScrollbarWidth = 20

    def __init__(self, model):
        self.model = model
        self._selectedCorners = []
        self.sheetCoordinates = list(range(4))
        self.scanCanvas = None
        self.previewCanvas = None
        self.buttonFrame = None
        self.scrollPreviewY = None
        self.setActiveSheet(None)
        self.loadConfig()
        self.readyForTagRecognition = False

        width = self.model.db.config.getint('general', 'screen_width')
        width = None if width == -1 else width
        height = self.model.db.config.getint('general', 'screen_height')
        height = None if height == -1 else height
        super().__init__(width, height)

    def rotateImage90(self, event = None):
        self.rotationAngle = (self.rotationAngle + 90) % 360
        self.populateRoot()

    def populateRoot(self):
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
        resizedImgHeight, resizedImgWidth = int(o_h * aspectRatio), int(o_w * aspectRatio)
        resizedImg = cv.resize(rotatedImg, (resizedImgWidth, resizedImgHeight), Image.BILINEAR)

        # Note: it is necessary to store the image locally for tkinter to show it
        self.resizedImg = ImageTk.PhotoImage(Image.fromarray(resizedImg))
        if self.scanCanvas is None:
            self.scanCanvas = tkinter.Canvas(self.root)
        self.scanCanvas.place(x = 0,
            y = 0,
            width = resizedImgWidth,
            height = resizedImgHeight)
        self.scanCanvas.bind("<Button-1>", self.onMouseDownOnScanCanvas)
        self.scanCanvas.bind("<Motion>", self.onMouseMotionOnScanCanvas)
        self.resetScanCanvas(None, None)

        # preview of split sheets with the current configuration
        if self.previewCanvas is None:
            self.previewCanvas = tkinter.Canvas(self.root)
        self.previewCanvas.place(x = resizedImgWidth,
            y = 0,
            width = self.width - self.buttonFrameWidth - self.previewScrollbarWidth - resizedImgWidth,
            height = self.height)
        self.previewCanvas.configure(scrollregion=self.previewCanvas.bbox("all"))
        self.previewCanvas.bind('<Button-1>', self.onMouseDownOnPreviewCanvas)
        if sys.platform == "linux" or sys.platform == "linux2" or sys.platform == "darwin":
            self.previewCanvas.bind("<Button-4>", self.onMouseWheelOnPreviewCanvas)
            self.previewCanvas.bind("<Button-5>", self.onMouseWheelOnPreviewCanvas)
        elif sys.platform == "win32":
            self.previewCanvas.bind("<MouseWheel>", self.onMouseWheelOnPreviewCanvas)

        if self.scrollPreviewY is None:
            self.scrollPreviewY = tkinter.Scrollbar(self.root, orient='vertical', command=self.previewCanvas.yview)
        self.scrollPreviewY.place(
                x = self.width - self.buttonFrameWidth - self.previewScrollbarWidth,
                y = 0,
                width = self.previewScrollbarWidth,
                height = self.height)
        self.previewCanvas.configure(yscrollcommand=self.scrollPreviewY.set)

        self.previewCanvas.update()
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
        buttons = []
        buttons.append(('loadConfig', 'Load configuration',
            self.loadConfigAndResetGUI))
        buttons.append(('saveConfig', 'Save configuration', self.saveConfig))
        buttons.append(('rotateImage90', 'Rotate image', self.rotateImage90))
        for idx in range(4):
            buttons.append((f'activateSheet{idx}', f'Edit sheet {idx}',
                functools.partial(self.setActiveSheet, idx)))
        buttons.append(('splitSheets', 'Split sheets', self.splitSheets))
        buttons.append(('recognizeTags', 'Recognize tags', self.recognizeTags))
        self.addButtonFrame(buttons)
        if self.readyForTagRecognition:
            self.buttons['recognizeTags'].config(state='normal')
        else:
            self.buttons['recognizeTags'].config(state='disabled')

    def loadConfigAndResetGUI(self, event = None):
        self.loadConfig()
        self.populateRoot()

    def loadConfig(self):
        self.rotationAngle = self.model.db.config.getint('tagtrail_ocr', 'rotationAngle')
        self.sheetCoordinates[0] = list(map(float,
            self.model.db.config.getcsvlist('tagtrail_ocr', 'sheet0_coordinates')))
        self.sheetCoordinates[1] = list(map(float,
            self.model.db.config.getcsvlist('tagtrail_ocr', 'sheet1_coordinates')))
        self.sheetCoordinates[2] = list(map(float,
            self.model.db.config.getcsvlist('tagtrail_ocr', 'sheet2_coordinates')))
        self.sheetCoordinates[3] = list(map(float,
            self.model.db.config.getcsvlist('tagtrail_ocr', 'sheet3_coordinates')))

    def saveConfig(self, event = None):
        self.model.db.config.set('tagtrail_ocr', 'rotationAngle', str(self.rotationAngle))
        self.model.db.config.set('tagtrail_ocr', 'sheet0_coordinates', str(', '.join(map(str, self.sheetCoordinates[0]))))
        self.model.db.config.set('tagtrail_ocr', 'sheet1_coordinates', str(', '.join(map(str, self.sheetCoordinates[1]))))
        self.model.db.config.set('tagtrail_ocr', 'sheet2_coordinates', str(', '.join(map(str, self.sheetCoordinates[2]))))
        self.model.db.config.set('tagtrail_ocr', 'sheet3_coordinates', str(', '.join(map(str, self.sheetCoordinates[3]))))
        self.model.db.writeConfig()

    def setActiveSheet(self, index, event = None):
        self.activeSheetIndex = index

    def onMouseDownOnScanCanvas(self, event):
        if self.activeSheetIndex is None:
            return

        if len(self._selectedCorners) < 2:
            self._selectedCorners.append(Corner(event.x, event.y))

        if len(self._selectedCorners) == 2:
            self.root.update()
            canvasWidth = self.scanCanvas.winfo_width()
            canvasHeight = self.scanCanvas.winfo_height()
            self.sheetCoordinates[self.activeSheetIndex] = [
                    self._selectedCorners[0].x / canvasWidth,
                    self._selectedCorners[0].y / canvasHeight,
                    self._selectedCorners[1].x / canvasWidth,
                    self._selectedCorners[1].y / canvasHeight
                    ]
            self._selectedCorners = []
            self.setActiveSheet(None)

        self.resetScanCanvas(event.x, event.y)

    def onMouseMotionOnScanCanvas(self, event):
        if self.activeSheetIndex is None:
            return
        self.resetScanCanvas(event.x, event.y)

    def resetScanCanvas(self, x = None, y = None):
        self.scanCanvas.delete("all")
        self.scanCanvas.create_image(0,0, anchor=tkinter.NW, image=self.resizedImg)

        for corner in self._selectedCorners:
            r = 2
            self.scanCanvas.create_oval(
                    corner.x-r,
                    corner.y-r,
                    corner.x+r,
                    corner.y+r,
                    outline = 'red')

        self.root.update()
        canvasWidth = self.scanCanvas.winfo_width()
        canvasHeight = self.scanCanvas.winfo_height()
        sheetColors = ['green', 'blue', 'red', 'orange']
        for sheetIndex, sheetCoords in enumerate(self.sheetCoordinates):
            if sheetIndex == self.activeSheetIndex:
                if len(self._selectedCorners) == 1:
                    self.scanCanvas.create_rectangle(
                            self._selectedCorners[0].x,
                            self._selectedCorners[0].y,
                            x,
                            y,
                            outline = sheetColors[sheetIndex],
                            width = 2)
                elif len(self._selectedCorners) == 2:
                    self.scanCanvas.create_rectangle(
                            self._selectedCorners[0].x,
                            self._selectedCorners[0].y,
                            self._selectedCorners[1].x,
                            self._selectedCorners[1].y,
                            outline = sheetColors[sheetIndex],
                            width = 2)
            else:
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
        self.logger.debug(f'clicked at {event.x}, {event.y} - ({x}, {y}) on canvas')

        row = int(y // self.previewRowHeight)
        col = int(x // self.previewColumnWidth)
        sheetRegionIdx = row*self.previewColumnCount + col
        self.logger.debug(f'clicked on preview {sheetRegionIdx}, row={row}, col={col}')
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

    def onMouseWheelOnPreviewCanvas(self, event):
        increment = 0
        # respond to Linux or Windows wheel event
        if event.num == 5 or event.delta < 0:
            increment = 1
        if event.num == 4 or event.delta > 0:
            increment = -1
        self.previewCanvas.yview_scroll(increment, "units")

    def splitSheets(self, event = None):
        self.readyForTagRecognition = False

        self.setupProgressIndicator()
        self.model.prepareScanSplitting()
        for scanFileIndex, scanFilename in enumerate(self.model.scanFilenames):
            if self.abortingProcess:
                break
            self.updateProgressIndicator(scanFileIndex /
                    len(self.model.scanFilenames) * 100,
                    f'Splitting {scanFilename}')

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

    def recognizeTags(self, event = None):
        if (self.model.sheetRegions == [] or
                self.readyForTagRecognition == False):
            messagebox.showerror('Sheets missing', 'Unable to recognize tags - input images need to be split first')
            return

        self.setupProgressIndicator()
        self.model.prepareTagRecognition()
        with self.model:
            for idx, sheetRegion in enumerate(self.model.sheetRegions):
                if self.abortingProcess:
                    break
                self.updateProgressIndicator(idx / len(self.model.sheetRegions)
                        * 100, sheetRegion.name)
                self.model.recognizeTags(sheetRegion)

        self.destroyProgressIndicator()

        if self.abortingProcess:
            return

        if messagebox.askyesno('OCR completed',
                'tagtrail_ocr is done - exit now?'):
            self.root.destroy()

def main(rootDir, individualScanFilename, tmpDir, writeDebugImages):
    helpers.recreateDir(tmpDir)

    scanDir = f'{rootDir}0_input/scans/'
    scanFilenames, clearOutputDir = None, None
    if individualScanFilename is None:
        for (parentDir, dirNames, filenames) in os.walk(scanDir):
            scanFilenames = filenames
            break
        clearOutputDir = True
    else:
        scanFilenames = [individualScanFilename]
        clearOutputDir = False

    model = Model(rootDir, tmpDir, scanFilenames, clearOutputDir,
            writeDebugImages)
    gui = GUI(model)
    if model.sheetRegions == [] or gui.abortingProcess:
        return

    gui.logger.info(f'Successfully processed {len(scanFilenames)} files')
    gui.logger.info(f'The following files generated less than {ScanSplitter.numberOfSheets} sheets:')
    for f in model.partiallyFilledFiles:
        gui.logger.info(f' * {f}')

if __name__== "__main__":
    parser = argparse.ArgumentParser(
        description='Recognize tags on all input scans, storing them as CSV files')
    parser.add_argument('rootDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    parser.add_argument('--individualScan', dest='individualScanFilename',
            help='''Filename of a single new scan to be processed. Using this
            option, already processed product sheets will not be overwritten or
            discarded, unless they stem from the same scan.''')
    parser.add_argument('--tmpDir', dest='tmpDir', default='data/tmp/',
            help='Directory to put temporary files in')
    parser.add_argument('--writeDebugImages', dest='writeDebugImages', action='store_true')
    parser.add_argument('--logLevel', dest='logLevel',
            help='Log level to write to console', default='INFO')
    args = parser.parse_args()
    helpers.configureLogger(logging.getLogger('tagtrail'), consoleLevel =
            logging.getLevelName(args.logLevel))
    main(args.rootDir, args.individualScanFilename, args.tmpDir, args.writeDebugImages)
