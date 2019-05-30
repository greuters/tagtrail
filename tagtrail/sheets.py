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
from helpers import Log
from abc import ABC, abstractmethod
from PIL import ImageFont, Image, ImageDraw
random.seed()

class ProductSheet(ABC):
    # Sheet Dimensions
    pageMargin = 10 # mm
    layoutMargin = 15 # mm
    xRes = 2480 # px
    yRes = 3508 # px
    sheetW = 210 # mm
    sheetH = 297 # mm

    # Layout (all widths/heights in mm)
    headerH = 15
    nameW = 100
    unitW = 30
    priceW = 50
    dataBgColors = [[220, 220, 220], [190, 190, 190]]
    dataColCount = 6
    dataRowCount = 16
    dataRowW = 30
    dataColH = 15

    @classmethod
    def maxQuantity(self):
        return self.dataColCount*self.dataRowCount

    @classmethod
    def getPageMarginPts(self):
        return (self.pointFromMM(self.pageMargin, self.pageMargin),
                self.pointFromMM(self.sheetW-self.pageMargin, self.sheetH-self.pageMargin))

    @classmethod
    def pointFromMM(self, u, v):
        return (round(u / self.sheetW * self.xRes),
                round(v / self.sheetH * self.yRes))

    def __init__(self, name, unit, price, quantity, database=None,
            testMode=False):
        self.name=name
        self.unit=unit
        self.price=price
        self.quantity=quantity
        self._database=database
        self.testMode=testMode
        self._boxes=[]
        self._log=Log()

        # Page margin (for easier OCR)
        p0, p1 = self.getPageMarginPts()
        self._boxes.append(Box("marginBox", p0, p1, (235,235,235), lineW=20))

        # Header
        u0 = self.layoutMargin
        v0 = self.layoutMargin
        u1 = u0+self.nameW
        v1 = v0+self.headerH
        self._boxes.append(Box(
                "nameBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1],
                self.name))

        u0 = u1
        u1 = u0+self.unitW
        self._boxes.append(Box(
                "unitBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1],
                self.unit))

        u0 = u1
        u1 = u0+self.priceW
        self._boxes.append(Box(
                "priceBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1],
                self.price))

        # Data
        for (col, row) in itertools.product(range(0,self.dataColCount),
                range(0,self.dataRowCount)):
            v0 = self.layoutMargin + self.headerH//2 + (row+1)*self.dataColH
            color = self.dataBgColors[row % 2]
            num = col*self.dataRowCount + row
            if num == self.quantity:
                break
            u0 = self.layoutMargin + col*self.dataRowW
            if self.testMode:
                if self._database:
                    text = self._database._members[random.randint(0,
                        len(self._database._members)-1)]._id
                else:
                    text = "Test"
                textRotation = random.randrange(-8,8)
            else:
                text = ""
                textRotation = 0

            self._boxes.append(Box(
                    "dataBox{}({},{})".format(num,col,row),
                    self.pointFromMM(u0, v0),
                    self.pointFromMM(u0+self.dataRowW, v0+self.dataColH),
                    color,
                    text,
                    textRotation=textRotation
                    ))


    def createImg(self):
        img = np.full((self.yRes, self.xRes, 3), 255, np.uint8)
        for box in self._boxes:
            box.draw(img)
        return img

class Box(ABC):
    fontColor = 'black'
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                50)

    def __init__(self, name, pt1, pt2, bgColor,
            text = "",
            lineW = 3,
            lineColor = [0, 0, 0],
            textRotation = 0):
        self.name = name
        self.pt1 = pt1
        self.pt2 = pt2
        self.bgColor = bgColor
        self.text = text
        self.lineW = lineW
        self.lineColor = lineColor
        self.textRotation = textRotation
        self._log = Log()

    def draw(self, img):
        cv.rectangle(img, self.pt1, self.pt2, self.bgColor, -1)
        (x1, y1) = self.pt1
        (x2, y2) = self.pt2
        cv.line(img, (x1, y1), (x2,y1), self.lineColor, self.lineW)
        cv.line(img, (x1, y1), (x1,y2), self.lineColor, self.lineW)
        cv.line(img, (x2, y1), (x2,y2), self.lineColor, self.lineW)
        cv.line(img, (x1, y2), (x2,y2), self.lineColor, self.lineW)

        if self.text != "":
            textW, textH = self.font.getsize(self.text)
            self._log.debug("textW={}, textH={}".format(textW, textH))
            textX = x1 + round(((x2-x1) - textW) / 2)
            textY = y1 + round(((y2-y1) - textH) / 2)
            img_rgb = cv.cvtColor(img[textY:textY+textH,textX:textX+textW], cv.COLOR_BGR2RGB)
            canvas = Image.fromarray(img_rgb)
            draw = ImageDraw.Draw(canvas)
            draw.text((0,0), self.text, self.fontColor, self.font)
            textImg = cv.cvtColor(np.array(canvas), cv.COLOR_RGB2BGR)

            # for testing OCR capabilities
            if self.textRotation != 0:
                rotMatrix = cv.getRotationMatrix2D((textH/2, textW/2),
                        self.textRotation, 1)
                textImg = cv.warpAffine(textImg, rotMatrix, (textW, textH), borderMode=cv.BORDER_CONSTANT,
                        borderValue=(255, 255, 255))
            img[textY:textY+textH,textX:textX+textW] = textImg
