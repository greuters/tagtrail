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
    priceW = 30
    pageNumberW = 20
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

    def __init__(self, name, unit, price, pageNumber, quantity, database=None,
            testMode=False):
        self.quantity=quantity
        self._database=database
        self.testMode=testMode
        self._boxes={}
        self._log=Log()
        self._box_to_pos={}
        self._pos_to_box={}

        # Page margin (for easier OCR)
        p0, p1 = self.getPageMarginPts()
        self._boxes["marginBox"] = Box("marginBox", p0, p1, (235,235,235), lineW=20)

        # Header
        u0 = self.layoutMargin
        v0 = self.layoutMargin
        u1 = u0+self.nameW
        v1 = v0+self.headerH
        self.addBox(Box(
                "nameBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1],
                name), 0, 0)

        u0 = u1
        u1 = u0+self.unitW
        self.addBox(Box(
                "unitBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1],
                unit), 0, 1)

        u0 = u1
        u1 = u0+self.priceW
        self.addBox(Box(
                "priceBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1],
                price), 0, 2)

        u0 = u1
        u1 = u0+self.pageNumberW
        self.addBox(Box(
                "pageNumberBox",
                self.pointFromMM(u0, v0),
                self.pointFromMM(u1, v1),
                self.dataBgColors[1],
                str(pageNumber)), 0, 3)

        # Data
        for (row, col) in itertools.product(range(0,self.dataRowCount),
                range(0,self.dataColCount)):
            v0 = self.layoutMargin + self.headerH//2 + (row+1)*self.dataColH
            color = self.dataBgColors[row % 2]
            num = row*self.dataColCount + col
            if num == self.quantity:
                break
            u0 = self.layoutMargin + col*self.dataRowW
            if self.testMode:
                if self._database:
                    text = list(self._database._members.values())[random.randint(0,
                        len(self._database._members)-1)]._id
                else:
                    text = "Test"
                textRotation = random.randrange(-8,8)
            else:
                text = ""
                textRotation = 0

            self.addBox(Box(
                    "dataBox{}({},{})".format(num,row,col),
                    self.pointFromMM(u0, v0),
                    self.pointFromMM(u0+self.dataRowW, v0+self.dataColH),
                    color,
                    text,
                    textRotation=textRotation
                    ), row+1, col)

    def addBox(self, box, row, col):
        self._boxes[box.name]=box
        pos = (row, col)
        self._box_to_pos[box]=pos
        self._pos_to_box[pos]=box

    def sortedPositions(self):
        return sorted(self._pos_to_box.keys(), key = lambda pos:
                pos[0]*ProductSheet.dataRowCount + pos[1])

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

    def createImg(self):
        img = np.full((self.yRes, self.xRes, 3), 255, np.uint8)
        for box in self._boxes.values():
            box.draw(img)
        return img

    def load(self, path):
        skipCnt=1
        csvDelimiter = ';'
        quotechar = '"'

        numDataBoxes = 0
        with open(path, newline='') as csvfile:
            reader = csv.reader(csvfile, delimiter=csvDelimiter,
                    quotechar=quotechar)
            for cnt, row in enumerate(reader):
                if cnt<skipCnt:
                    continue
                self._log.debug("row={}", row)
                boxName, text, confidence = row[0], row[1], float(row[2])
                if boxName == "marginBox":
                    continue
                elif boxName.find("dataBox") != -1:
                    numDataBoxes += 1
                elif boxName not in ("nameBox", "unitBox", "priceBox", "pageNumberBox"):
                    self._log.warn("skipped unexpected box, row = {}", row)
                self._boxes[boxName].name = boxName
                self._boxes[boxName].text = text
                self._boxes[boxName].confidence = confidence

    def store(self, path):
        filePath = "{}{}_{}.csv".format(path, self._boxes['nameBox'].text,
                self._boxes['pageNumberBox'].text)
        self._log.info("storing sheet {}".format(filePath))
        with open(filePath, "w+") as fout:
            fout.write("{};{};{}\n" .format("boxName", "text", "confidence"))
            for box in self._boxes.values():
                fout.write("{};{};{}\n".format(box.name, box.text, box.confidence))

class Box(ABC):
    fontColor = 'black'
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                50)

    def __init__(self, name, pt1, pt2, bgColor,
            text = "",
            confidence = 1,
            lineW = 3,
            lineColor = [0, 0, 0],
            textRotation = 0):
        self.name = name
        self.pt1 = pt1
        self.pt2 = pt2
        self.bgColor = bgColor
        self.text = text
        self.confidence = confidence
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
