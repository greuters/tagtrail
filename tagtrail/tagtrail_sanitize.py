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
import slugify
import tkinter
from tkinter import ttk
from tkinter import messagebox
import re
import os
from PIL import ImageTk,Image
from sheets import ProductSheet
from database import Database
from helpers import Log
import random
import traceback
import gui_components

class InputSheet(ProductSheet):
    validationProbability = 0.05

    def __init__(self, root, aspectRatio,
            database, path):
        super().__init__()
        self.load(path)
        self.originalPath = path

        self._box_to_widget = {}
        self.validationBoxTexts = {}
        for box in self.boxes():
            if box.name == "nameBox":
                choices = list(sorted([p.description
                    for p in database.products.values()]))
            elif box.name == "unitBox":
                choices = list(sorted([p.amountAndUnit
                    for p in database.products.values()]))
            elif box.name == "priceBox":
                choices = list(sorted([str(p.grossSalesPrice())
                    for p in database.products.values()]))
            elif box.name == "pageNumberBox":
                choices = [str(x) for x in range(1, 100)]
            elif box.name.find("dataBox") != -1:
                choices = list(sorted(database.members.keys()))
            else:
                continue

            # TODO make this concept more clear
            # prepare for OCR validation
            # 1. select some boxes with high confidence
            # 2. let the user correct them
            # 3. check if any of the boxes had a wrong value - must not happen
            v = random.uniform(0, 1)
            if box.confidence == 1 and \
                ( \
                    (box.text == '' and v < (self.validationProbability / 10.0)) \
                or \
                    (box.text != '' and v < self.validationProbability) \
                ):
                self.validationBoxTexts[box.name] = box.text
                box.confidence = 0

            (x1, y1) = box.pt1
            x1, y1 = x1*aspectRatio, y1*aspectRatio
            (x2, y2) = box.pt2
            x2, y2 = x2*aspectRatio, y2*aspectRatio
            entry = gui_components.AutocompleteEntry(box.text, box.confidence, choices, self.switchFocus, root)
            entry.place(x=x1, y=y1, w=x2-x1, h=y2-y1)
            entry.box = box
            self._box_to_widget[box] = entry

        self._box_to_widget[self.boxByName('nameBox')].focus_set()

    def switchFocus(self, event):
        # cudos to https://www.daniweb.com/programming/software-development/code/216830/tkinter-keypress-event-python
        if str(event.type) == "KeyPress" and event.char != event.keysym:
            # punctuation or special key, distinguish by event.keysym
            if event.keysym in ["Return", "Tab"]:
                if event.keysym == "Return":
                    event.widget.confidence=1
                event.widget.box.text = event.widget.text
                event.widget.box.confidence = event.widget.confidence

                nextBox = self.nextUnclearBox(event.widget.box)
                if nextBox:
                    self._box_to_widget[nextBox].focus_set()

            elif event.keysym in ["Up", "Down", "Left", "Right"]:
                event.widget.box.text = event.widget.text
                event.widget.box.confidence = event.widget.confidence

                neighbourBox = self.neighbourBox(event.widget.box, event.keysym)
                if neighbourBox:
                    self._box_to_widget[neighbourBox].focus_set()

        return event

    def nextUnclearBox(self, selectedBox):
        sortedBoxes = self.sortedBoxes()
        indicesOfUnclearBoxes = [idx for idx, b in enumerate(sortedBoxes) if b.confidence<1]
        if not indicesOfUnclearBoxes:
            return None
        else:
            currentIndex = sortedBoxes.index(selectedBox)
            if max(indicesOfUnclearBoxes) <= currentIndex:
                return sortedBoxes[min(indicesOfUnclearBoxes)]
            else:
                return sortedBoxes[min(filter(lambda x: currentIndex < x,
                    indicesOfUnclearBoxes))]

    def getValidationScore(self):
        numCorrect = 0
        numValidated = 0
        for box in self.boxes():
            if box.name in self.validationBoxTexts and box.confidence == 1:
                numValidated += 1
                if self.validationBoxTexts[box.name] == box.text:
                    numCorrect += 1

        return (numCorrect, numValidated)

class Gui:
    scanPostfix = '_normalized_scan.jpg'

    def __init__(self, accountingDataPath):
        # TODO: add second dataPath - for each csv, check if the corresponding
        # csv existed in the last accounting. if a box has a (validated, assert
        # confidence = 1) non '' text, override the ocr suggestion and set
        # confidence to 1
        self.log = Log()
        self.accountingDataPath = accountingDataPath
        self.productPath = f'{self.accountingDataPath}2_taggedProductSheets/'
        self.db = Database(f'{self.accountingDataPath}0_input/')
        self.numCorrectValidatedBoxes = 0
        self.numValidatedValidatedBoxes = 0

        self.root = tkinter.Tk()
        self.root.report_callback_exception = self.reportCallbackException
        self.buttonCanvasWidth=200
        self.width=self.root.winfo_screenwidth()
        self.height=self.root.winfo_screenheight()
        self.root.geometry(str(self.width)+'x'+str(self.height))
        self.root.bind("<Tab>", self.switchInputFocus)
        self.root.bind("<Return>", self.switchInputFocus)
        self.root.bind("<Up>", self.switchInputFocus)
        self.root.bind("<Down>", self.switchInputFocus)
        self.root.bind("<Left>", self.switchInputFocus)
        self.root.bind("<Right>", self.switchInputFocus)

        self.pairToSanitizeGenerator = self.nextPairToSanitize()
        try:
            self.csvPath, self.scanPath = next(self.pairToSanitizeGenerator)
        except StopIteration:
            messagebox.showinfo('Nothing to do',
                f'No file needing sanitation in input path {self.productPath}')
            self.root.destroy()
        else:
            self.loadProductSheet()

        self.root.mainloop()

    def reportCallbackException(self, exception, value, tb):
        traceback.print_exception(exception, value, tb)
        messagebox.showerror('Abort Accounting', value)

    def nextPairToSanitize(self):
        # assuming each product is stored in productPath as a pair of
        # ({productName}_{page}.csv, {productName}_{page}_normalized_scan.jpg)
        csvFiles = None
        for (_, _, fileNames) in os.walk(self.productPath):
            csvFiles = sorted(filter(lambda f: os.path.splitext(f)[1] ==
                '.csv', fileNames))
            scanFiles = sorted(filter(lambda f: f.find(self.scanPostfix)
                != -1, fileNames))
            break

        if not csvFiles:
            raise StopIteration

        foundPairToSanitize = False
        for csvFile in csvFiles:
            scanFile = os.path.splitext(csvFile)[0] + self.scanPostfix
            if scanFile in scanFiles:
                # check if this csv needs sanitation
                sheet = ProductSheet()
                sheet.load(self.productPath + csvFile)
                if list(filter(lambda box: box.confidence < 1,
                    sheet.boxes())):
                    foundPairToSanitize = True
                    yield (self.productPath + csvFile, self.productPath + scanFile)
            else:
                self.log.warn('{} omitted, corresponding scan is missing'
                        .format(csvFile))

        if foundPairToSanitize:
            # start a new round, as there are still files to sanitize
            for p in self.nextPairToSanitize():
                yield p

    def saveAndContinue(self, event=None):
        self.save()
        try:
            self.csvPath, self.scanPath = next(self.pairToSanitizeGenerator)
        except StopIteration:
            if self.numCorrectValidatedBoxes == self.numValidatedValidatedBoxes:
                messagebox.showinfo('Sanitation complete',
                    'Congratulations, your work is done')
            else:
                messagebox.showwarning('Sanitation complete',
                    """
                    Your work is done, but OCR didn't work properly.
                    You corrected {} out of {} validated texts. Apparently OCR
                    was overconfident and probably some of the initially green
                    boxes contain wrong entries. Please check them and file a
                    bug report at https://github.com/greuters/tagtrail.git/
                    """)
            self.root.destroy()
        else:
            self.destroyCanvas()
            self.loadProductSheet()
            return "break"

    def saveAndReloadDB(self, event=None):
        self.save()
        self.db = Database(f'{self.accountingDataPath}0_input/')
        self.loadProductSheet()
        return "break"

    def save(self):
        if not self.inputSheet.name:
            raise ValueError('Unable to store sheet, name is missing')
        if not self.inputSheet.amountAndUnit:
            raise ValueError('Unable to store sheet, amountAndUnit is missing')
        if not self.inputSheet.grossSalesPrice:
            raise ValueError('Unable to store sheet, grossSalesPrice is missing')
        if not self.inputSheet.pageNumber:
            raise ValueError('Unable to store sheet, pageNumber is missing')

        numCorrect, numValidated = self.inputSheet.getValidationScore()
        self.numCorrectValidatedBoxes += numCorrect
        self.numValidatedValidatedBoxes += numValidated
        self.log.info(f'sheet validation score: {numCorrect} ' + \
                f'out of {numValidated} validated texts were correct')
        self.log.info(f'total validation score: ' + \
                f'{self.numCorrectValidatedBoxes} out of ' + \
                f'{self.numValidatedValidatedBoxes} validated texts were correct')
        os.remove(self.csvPath)
        self.inputSheet.store(self.productPath)
        os.rename(self.scanPath, "{}{}_{}{}".format(self.productPath,
            self.inputSheet.productId(),
            self.inputSheet.pageNumber,
            self.scanPostfix))
        self.destroyCanvas()

    def destroyCanvas(self):
        self.scanCanvas.destroy()
        self.inputCanvas.destroy()
        self.buttonCanvas.destroy()

    def loadProductSheet(self):
        # Scanned input image
        # Note: it is necessary to store the image locally for tkinter to show it
        self.scannedImg = Image.open(self.scanPath)
        o_w, o_h = self.scannedImg.size
        aspectRatio = min(self.height / o_h, (self.width - self.buttonCanvasWidth) / 2 / o_w)
        canvas_w, canvas_h = int(o_w * aspectRatio), int(o_h * aspectRatio)
        self.scannedImg = self.scannedImg.resize((canvas_w, canvas_h), Image.BILINEAR)
        self.scannedImg = ImageTk.PhotoImage(self.scannedImg)
        self.scanCanvas = tkinter.Canvas(self.root,
               width=canvas_w,
               height=canvas_h)
        self.scanCanvas.place(x=0, y=0)
        self.scanCanvas.create_image(0,0, anchor=tkinter.NW, image=self.scannedImg)
        self.__focusAreaImage = None
        self.__focusAreaBorderRect = None

        # Input mask to correct product sheet
        self.inputCanvas = tkinter.Canvas(self.root,
               width=canvas_w,
               height=canvas_h)
        self.inputCanvas.place(x=canvas_w, y=0)
        self.inputSheet = InputSheet(self.inputCanvas, aspectRatio, self.db, self.csvPath)

        # Additional buttons
        self.buttonCanvas = tkinter.Frame(self.root,
               width=self.buttonCanvasWidth,
               height=canvas_h)
        self.buttonCanvas.place(x=2*canvas_w, y=0)
        self.buttons = {}
        self.buttons['saveAndContinue'] = tkinter.Button(self.buttonCanvas, text='Save and continue',
            command=self.saveAndContinue)
        self.buttons['saveAndContinue'].bind('<Return>', self.saveAndContinue)
        self.buttons['saveAndReloadDB'] = tkinter.Button(self.buttonCanvas,
            text='Save and reload current',
            command=self.saveAndReloadDB)
        self.buttons['saveAndReloadDB'].bind('<Return>', self.saveAndReloadDB)

        y = 60
        for b in self.buttons.values():
            b.place(relx=.5, y=y, anchor="center",
                    width=.8*self.buttonCanvasWidth)
            b.update()
            y += b.winfo_height()

    def switchInputFocus(self, event):
        focused = self.root.focus_displayof()
        if not focused:
            return event
        elif isinstance(focused, gui_components.AutocompleteEntry):
            if focused.confidence == 1 and event.keysym in ('Tab', 'Return'):
                self.buttons['saveAndContinue'].focus_set()
            else:
                info = focused.place_info()
                self.setFocusAreaOnScan(int(info['x']), int(info['y']),
                        int(info['width']), int(info['height']))
        elif event.keysym == 'Tab':
            focused.tk_focusNext().focus_set()
        else:
            return event
        return 'break'

    def setFocusAreaOnScan(self, x, y, width, height):
        if self.__focusAreaImage:
            self.scanCanvas.delete(self.__focusAreaImage)
            self.scanCanvas.delete(self.__focusAreaBorderRect)

        # cudos to https://stackoverflow.com/questions/54637795/how-to-make-a-tkinter-canvas-rectangle-transparent
        alpha = 80
        self.__focusAreaImageSrc = ImageTk.PhotoImage(Image.new('RGBA',
            (width, height),
            self.root.winfo_rgb('green') + (alpha,)))
        self.__focusAreaImage = self.scanCanvas.create_image(x, y, image=self.__focusAreaImageSrc, anchor='nw')
        self.__focusAreaBorderRect = self.scanCanvas.create_rectangle(x, y,
                x+width, y+height)

if __name__== "__main__":
    parser = argparse.ArgumentParser(
        description='Go through all tags recognized by tagtrail_ocr, ' + \
                'completing missing tags and validating recognized ones.')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    args = parser.parse_args()
    # TODO: check that only valid member ids and product ids are stored for new
    # tags (that are not in previous accounting)
    # product files need to have product ids in file names
    Gui(args.accountingDir)
