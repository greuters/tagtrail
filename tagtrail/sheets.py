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
import datetime
import decimal
import itertools
import random
import csv
from abc import ABC, abstractmethod
from PIL import ImageFont, Image, ImageDraw
import slugify

from . import helpers
random.seed()

class ProductSheet(ABC):
    # Sheet Dimensions
    topSheetFrame = 20 # mm
    bottomSheetFrame = 15 # mm
    leftSheetFrame = 15 # mm
    rightSheetFrame = 15 # mm
    topMargin = 25 # mm
    leftMargin = 20 # mm
    xRes = 2480 # px
    yRes = 3508 # px
    sheetW = 210 # mm
    sheetH = 297 # mm

    # Layout (all widths/heights in mm)
    headerH = 15
    nameW = 85
    unitW = 30
    priceW = 30
    sheetNumberW = 25
    dataBgColors = [[220, 220, 220], [190, 190, 190]]
    dataColCount = 5
    dataRowCount = 15
    dataRowW = 34
    dataColH = 15

    @classmethod
    def maxQuantity(self):
        return self.dataColCount*self.dataRowCount

    @classmethod
    def getSheetFramePts(self):
        return (self.pointFromMM(self.leftSheetFrame, self.topSheetFrame),
                self.pointFromMM(self.sheetW-self.rightSheetFrame,
                    self.sheetH-self.bottomSheetFrame))

    @classmethod
    def pointFromMM(self, u, v):
        return (round(u / self.sheetW * self.xRes),
                round(v / self.sheetH * self.yRes))

    def __init__(self, log = helpers.Log()):
        self._boxes={}
        self._log=log
        self._box_to_pos={}
        self._pos_to_box={}

        # Frame around sheet (for easier OCR)
        p0, p1 = self.getSheetFramePts()
        self._boxes["frameBox"] = Box("frameBox", p0, p1, (255,255,255), lineW=20)

        # Header
        u0 = self.leftMargin
        v0 = self.topMargin
        u1 = u0+self.nameW
        v1 = v0+self.headerH
        self.addBox(Box(
                "nameBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1]), 0, 0)

        u0 = u1
        u1 = u0+self.unitW
        self.addBox(Box(
                "unitBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1]), 0, 1)

        u0 = u1
        u1 = u0+self.priceW
        self.addBox(Box(
                "priceBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1]), 0, 2)

        u0 = u1
        u1 = u0+self.sheetNumberW
        self.addBox(Box(
                "sheetNumberBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1]), 0, 3)

        # Data
        for (row, col) in itertools.product(range(0,self.dataRowCount),
                range(0,self.dataColCount)):
            v0 = self.topMargin + self.headerH//2 + (row+1)*self.dataColH
            color = self.dataBgColors[row % 2]
            num = row*self.dataColCount + col
            u0 = self.leftMargin + col*self.dataRowW
            text = ""

            self.addBox(Box(
                    "dataBox{}({},{})".format(num,row,col),
                    self.pointFromMM(u0, v0),
                    self.pointFromMM(u0+self.dataRowW, v0+self.dataColH),
                    color,
                    text,
                    ), row+1, col)

    @property
    def name(self):
        return self._boxes['nameBox'].text

    @name.setter
    def name(self, name):
        self._boxes['nameBox'].text = name
        self._boxes['nameBox'].confidence = 1

    def productId(self):
        return slugify.slugify(self._boxes['nameBox'].text)

    @property
    def amountAndUnit(self):
        return self._boxes['unitBox'].text

    @amountAndUnit.setter
    def amountAndUnit(self, amountAndUnit):
        self._boxes['unitBox'].text = amountAndUnit
        self._boxes['unitBox'].confidence = 1

    @property
    def grossSalesPrice(self):
        return helpers.priceFromFormatted(self._boxes['priceBox'].text)

    @grossSalesPrice.setter
    def grossSalesPrice(self, grossSalesPrice):
        self._boxes['priceBox'].text = grossSalesPrice
        self._boxes['priceBox'].confidence = 1

    @property
    def sheetNumber(self):
        return self._boxes['sheetNumberBox'].text

    @sheetNumber.setter
    def sheetNumber(self, sheetNumber):
        self._boxes['sheetNumberBox'].text = sheetNumber
        self._boxes['sheetNumberBox'].confidence = 1

    def addBox(self, box, row, col):
        self._boxes[box.name]=box
        pos = (row, col)
        self._box_to_pos[box]=pos
        self._pos_to_box[pos]=box

    def sortedPositions(self):
        return sorted(self._pos_to_box.keys(), key = lambda pos:
                pos[0]*ProductSheet.dataRowCount + pos[1])

    def boxByName(self, name):
        return self._boxes[name]

    def boxes(self):
        return self._boxes.values()

    def dataBoxes(self):
        return [box for box in self._boxes.values() if
                box.name.find('dataBox') != -1]

    def sortedBoxes(self):
        return [self._pos_to_box[pos] for pos in self.sortedPositions()]

    def neighbourBox(self, box, direction):
        if box not in self._box_to_pos:
            return None

        row, col = self._box_to_pos[box]
        if direction == 'Up':
            row -= 1
        elif direction == 'Down':
            row += 1
        elif direction == 'Left':
            col -= 1
        elif direction == 'Right':
            col += 1
        else:
            return None

        neighbourPos = (row, col)
        if neighbourPos in self._pos_to_box:
            return self._pos_to_box[(row, col)]
        else:
            return None

    def isFull(self):
        if self.boxByName('nameBox').text == '':
            return False
        if self.boxByName('unitBox').text == '':
            return False
        if self.boxByName('priceBox').text == '':
            return False
        if self.boxByName('sheetNumberBox').text == '':
            return False
        return self.emptyDataBoxes() == []

    def emptyDataBoxes(self):
        return [box for box in self.dataBoxes() if box.text == '']

    def tagsAndConfidences(self):
        return [(box.text, box.confidence) for box in self.dataBoxes()]

    def confidentTags(self):
        return [tag for (tag, conf) in self.tagsAndConfidences() if conf == 1]

    def unconfidentTags(self):
        return [tag for (tag, conf) in self.tagsAndConfidences() if conf != 1]

    def createImg(self):
        img = np.full((self.yRes, self.xRes, 3), 255, np.uint8)
        for box in self._boxes.values():
            box.draw(img)
        return img

    def load(self, path):
        self._log.info(f'Loading {path}')
        skipCnt=1
        csvDelimiter = ';'
        quotechar = '"'

        numDataBoxes = 0
        with open(path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=csvDelimiter,
                    quotechar=quotechar)
            for cnt, row in enumerate(reader):
                if cnt<skipCnt:
                    continue
                self._log.debug("row={}", row)
                boxName, text, confidence = row[0], row[1], float(row[2])
                if boxName == "frameBox":
                    continue
                elif boxName.find("dataBox") != -1:
                    numDataBoxes += 1
                elif boxName not in ("nameBox", "unitBox", "priceBox", "sheetNumberBox"):
                    self._log.warn("skipped unexpected box, row = {}", row)
                    continue
                self._boxes[boxName].name = boxName
                self._boxes[boxName].text = text
                self._boxes[boxName].confidence = confidence

    @property
    def filename(self):
        return f'{self.productId()}_{self.sheetNumber}.csv'

    @classmethod
    def productId_from_filename(cls, filename):
        """
        Try to parse productId from filename.

        Expected filenames have the format 'productId_sheetNumber.csv'

        :param filename: filename of a :class: `ProductSheet`
        :type filename: str
        :return: assumed productId or None
        :rtype: str
        """
        if ('_' not in filename
                or len(filename.split('_')) != 2
                or not filename.endswith('.csv')):
            raise ValueError(f'{filename} has wrong format '
                   '(productId_sheetNumber.csv) expected')
        return filename.split('_')[0]

    @classmethod
    def sheetNumber_from_filename(cls, filename):
        """
        Try to parse the formatted sheetNumber from filename.

        Expected filenames have the format '{productId}_{sheetNumber}.csv',
        if no sheetNumber can be identified, None is returned

        :param filename: filename of a :class: `ProductSheet`
        :type filename: str
        :return: assumed formatted sheetNumber or None
        :rtype: str
        """
        if ('_' not in filename
                or len(filename.split('_')) != 2
                or not filename.endswith('.csv')):
            raise ValueError(f'{filename} has wrong format '
                   '(productId_sheetNumber.csv) expected')
        return filename.split('_')[1][:-4]

    def store(self, path):
        filePath = f'{path}{self.filename}'
        self._log.info(f'storing sheet {filePath}')
        with open(filePath, "w+", encoding='utf-8') as fout:
            fout.write(f'boxName;text;confidence\n')
            for box in self.boxes():
                fout.write(f'{box.name};{box.text};{box.confidence:.1f}\n')

class Box(ABC):
    fontColor = 'black'
    font = ImageFont.truetype("dejavu-fonts-ttf-2.37/ttf/DejaVuSans-Bold.ttf",
                50)

    def __init__(self, name, pt1, pt2, bgColor,
            text = "",
            confidence = 1,
            lineW = 3,
            lineColor = [0, 0, 0]):
        self.name = name
        self.pt1 = pt1
        self.pt2 = pt2
        self.bgColor = bgColor
        self.text = text
        self.confidence = confidence
        self.lineW = lineW
        self.lineColor = lineColor
        self._log = helpers.Log()

    @property
    def text(self):
        return self.__text

    @text.setter
    def text(self, text):
        if not isinstance(text, str):
            return ValueError(f'{text} is not a string')
        self.__text = text

    def draw(self, img):
        cv.rectangle(img, self.pt1, self.pt2, self.bgColor, -1)
        (x1, y1) = self.pt1
        (x2, y2) = self.pt2
        cv.line(img, (x1, y1), (x2,y1), self.lineColor, self.lineW)
        cv.line(img, (x1, y1), (x1,y2), self.lineColor, self.lineW)
        cv.line(img, (x2, y1), (x2,y2), self.lineColor, self.lineW)
        cv.line(img, (x1, y2), (x2,y2), self.lineColor, self.lineW)

        if self.text != "":
            self._log.debug(f"text={self.text}")
            textW, textH = self.font.getsize(self.text)
            self._log.debug(f"textW={textW}, textH={textH}")
            textX = x1 + round(((x2-x1) - textW) / 2)
            textY = y1 + round(((y2-y1) - textH) / 2)
            self._log.debug(f"textX={textX}, textY={textY}")
            img_rgb = cv.cvtColor(img[textY:textY+textH,textX:textX+textW], cv.COLOR_BGR2RGB)
            canvas = Image.fromarray(img_rgb)
            draw = ImageDraw.Draw(canvas)
            draw.text((0,0), self.text, self.fontColor, self.font)
            textImg = cv.cvtColor(np.array(canvas), cv.COLOR_RGB2BGR)
            img[textY:textY+textH,textX:textX+textW] = textImg
