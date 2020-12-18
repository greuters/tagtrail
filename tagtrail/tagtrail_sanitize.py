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
import random
import traceback

from .sheets import ProductSheet
from .database import Database
from .helpers import Log, formatPrice
from . import gui_components

class InputSheet(ProductSheet):
    validationProbability = 0.02
    maxEpectedListboxHeight = 200

    def __init__(self, root, database, path, sheetsPath):
        super().__init__(log=Log())
        self.sheetsPath = sheetsPath
        self.load(path)
        self.originalPath = path

        # prepare choices
        maxNumSheets = database.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')
        sheetNumberString = database.config.get('tagtrail_gen', 'sheet_number_string')
        sheetNumbers = [sheetNumberString.format(sheetNumber=str(n))
                            for n in range(1, maxNumSheets+1)]
        currency = database.config.get('general', 'currency')
        names, units, prices = map(set, zip(*[
            (p.description,
             p.amountAndUnit,
             formatPrice(p.grossSalesPrice(), currency))
            for p in database.products.values()]))

        scaleFactor = min(root.winfo_height() / self.yRes,
                root.winfo_width() / self.xRes)
        self._box_to_widget = {}
        self.validationBoxTexts = {}
        for box in self.boxes():
            box.copiedFromPreviousAccounting = False
            if box.name == "nameBox":
                choices = names
            elif box.name == "unitBox":
                choices = units
            elif box.name == "priceBox":
                choices = prices
            elif box.name == "sheetNumberBox":
                choices = sheetNumbers
            elif box.name.find("dataBox") != -1:
                choices = list(sorted(database.members.keys()))
            else:
                continue

            # TODO make this concept more clear or switch to a better system
            # (use boxes from already accounted sheets to check, make sure that
            # e.g. 100 boxes are checked at least, regularly distributed among
            # sheets)
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
            x1, y1 = x1*scaleFactor, y1*scaleFactor
            (x2, y2) = box.pt2
            x2, y2 = x2*scaleFactor, y2*scaleFactor
            listBoxY = y2
            if listBoxY + self.maxEpectedListboxHeight > root.winfo_height():
                listBoxY = y1 - self.maxEpectedListboxHeight

            entry = gui_components.AutocompleteEntry(box.text, box.confidence,
                    choices, self.releaseFocus, True, root, x1,
                    listBoxY, root)
            entry.place(x=x1, y=y1, w=x2-x1, h=y2-y1)
            entry.box = box
            self._box_to_widget[box] = entry

        self.loadTagsFromPreviousAccounting()
        nextUnclearBox = self.nextUnclearBox(None)
        if nextUnclearBox:
            self._box_to_widget[nextUnclearBox].focus_set()

    def releaseFocus(self, event):
        # cudos to https://www.daniweb.com/programming/software-development/code/216830/tkinter-keypress-event-python
        if str(event.type) == "KeyPress" and event.char != event.keysym:
            # punctuation or special key, distinguish by event.keysym
            if event.keysym == "Return":
                event.widget.confidence=1
            if event.widget.enabled:
                event.widget.box.text = event.widget.text
                event.widget.box.confidence = event.widget.confidence
                if event.widget.box.name in ['nameBox', 'sheetNumberBox']:
                    self.loadTagsFromPreviousAccounting()

            shift_pressed = (event.state & 0x1)
            if event.keysym == 'Return' and shift_pressed:
                # keep focus on current box, this is only used to confirm the
                # current selection
                return 'break'

            elif event.keysym in ["Tab", 'Return']:
                nextBox = self.nextUnclearBox(event.widget.box)
                if nextBox and event.state != 'Shift':
                    self._box_to_widget[nextBox].focus_set()

            elif event.keysym in ["Up", "Down", "Left", "Right"]:
                neighbourBox = self.neighbourBox(event.widget.box, event.keysym)
                if neighbourBox:
                    self._box_to_widget[neighbourBox].focus_set()

        return event

    def loadTagsFromPreviousAccounting(self):
        """
        Load tags from last accounting if name and sheetNumber of this sheet
        are clear and the sheet already existed.
        """
        if self.boxByName('nameBox').confidence != 1:
            return
        if  self.boxByName('sheetNumberBox').confidence != 1:
            return

        sheetName = f'{self.productId()}_{self.sheetNumber}.csv'
        activeSheetPath = f'{self.sheetsPath}/active/{sheetName}'
        inactiveSheetPath = f'{self.sheetsPath}/inactive/{sheetName}'
        if os.path.exists(activeSheetPath):
            self.loadTagsFromAccountedSheet(activeSheetPath)
        elif os.path.exists(inactiveSheetPath):
            self.loadTagsFromAccountedSheet(inactiveSheetPath)

    def loadTagsFromAccountedSheet(self, path):
        self._log.debug(f'loading previous tags from {path}')

        accountedSheet = ProductSheet()
        accountedSheet.load(path)
        if [box for box in accountedSheet.boxes()
                if box.confidence != 1.0]:
            raise ValueError(
                    f'{accountedSheetPath} has boxes with confidence != 1')
        if accountedSheet.productId() != self.productId():
            raise ValueError(f'{accountedSheetPath} has wrong productId ({accountedSheet.productId()} != {self.productId()})')
        if accountedSheet.sheetNumber != self.sheetNumber:
            raise ValueError(f'{accountedSheetPath} has wrong sheetNumber')

        for accountedBox in accountedSheet.boxes():
            self._log.debug(f'{accountedBox.name} : {accountedBox.text}')
            if accountedBox.text != '':
                inputBox = self.boxByName(accountedBox.name)
                inputBox.text = accountedBox.text
                inputBox.confidence = 1
                inputBox.copiedFromPreviousAccounting = True

                assert(inputBox in self._box_to_widget)
                autocompleteEntry = self._box_to_widget[inputBox]
                text = inputBox.text
                if text not in autocompleteEntry.possibleValues:
                    autocompleteEntry.possibleValues.append(text)
                autocompleteEntry.text = inputBox.text
                autocompleteEntry.confidence = inputBox.confidence
                autocompleteEntry.enabled = False
                autocompleteEntry.destroyListBox()

    def unlockBoxesFromPreviousAccounting(self):
        for box in self.boxes():
            if box.copiedFromPreviousAccounting == True:
                box.confidence = 0
                box.copiedFromPreviousAccounting = False
                autocompleteEntry = self._box_to_widget[box]
                autocompleteEntry.confidence = box.confidence
                autocompleteEntry.enabled = True

    def nextUnclearBox(self, selectedBox):
        if self.boxByName('nameBox').confidence != 1:
            return self.boxByName('nameBox')
        if  self.boxByName('sheetNumberBox').confidence != 1:
            return self.boxByName('sheetNumberBox')
        sortedBoxes = self.sortedBoxes()
        indicesOfUnclearBoxes = [idx for idx, b in enumerate(sortedBoxes) if b.confidence<1]
        if not indicesOfUnclearBoxes:
            return None
        else:
            currentIndex = 0 if selectedBox is None else sortedBoxes.index(selectedBox)
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

class GUI(gui_components.BaseGUI):
    originalScanPostfix = '_original_scan.jpg'
    normalizedScanPostfix = '_normalized_scan.jpg'

    def __init__(self, accountingDataPath, log = Log(Log.LEVEL_INFO)):
        self.accountingDataPath = accountingDataPath
        self.productPath = f'{self.accountingDataPath}2_taggedProductSheets/'
        self.sheetsPath = f'{self.accountingDataPath}0_input/sheets/'
        self.db = Database(f'{self.accountingDataPath}0_input/')
        self.numCorrectValidatedBoxes = 0
        self.numValidatedValidatedBoxes = 0
        self.scanCanvas = None
        self.inputFrame = None
        self.log = log

        self.productToSanitizeGenerator = self.nextProductToSanitize()
        try:
            self.csvPath = next(self.productToSanitizeGenerator)
        except StopIteration:
            messagebox.showinfo('Nothing to do',
                f'No file needing sanitation in input path {self.productPath}')
            return

        width = self.db.config.getint('general', 'screen_width')
        width = None if width == -1 else width
        height = self.db.config.getint('general', 'screen_height')
        height = None if height == -1 else height
        super().__init__(width, height, log)

    def populateRoot(self):
        self.root.title(self.csvPath)
        self.root.bind("<Tab>", self.switchInputFocus)
        self.root.bind("<Return>", self.switchInputFocus)
        self.root.bind("<Up>", self.switchInputFocus)
        self.root.bind("<Down>", self.switchInputFocus)
        self.root.bind("<Left>", self.switchInputFocus)
        self.root.bind("<Right>", self.switchInputFocus)

        canvasWidth = (self.width - self.buttonFrameWidth)/2
        if self.scanCanvas is None:
            self.scanCanvas = tkinter.Canvas(self.root)
        self.scanCanvas.delete("all")
        self.scanCanvas.place(x=0, y=0, width=canvasWidth, height=self.height)
        self.scanCanvas.update()
        self.scannedImgPath = self.csvPath+self.normalizedScanPostfix
        self.loadScannedImg()

        # Input mask to correct product sheet
        if self.inputFrame is None:
            self.inputFrame = tkinter.Frame(self.root)
        for w in self.inputFrame.winfo_children():
            w.destroy()
        self.inputFrame.place(x=canvasWidth, y=0, width=canvasWidth,
                height=self.height)
        self.inputFrame.update()
        self.inputSheet = InputSheet(self.inputFrame, self.db, self.csvPath,
                self.sheetsPath)

        self.root.update()
        focused = self.root.focus_displayof()
        info = focused.place_info()
        self.setFocusAreaOnScan(int(info['x']), int(info['y']),
                int(info['width']), int(info['height']))

        # Additional buttons
        buttons = []
        buttons.append(('saveAndContinue', 'Save and continue',
            self.saveAndContinue))
        buttons.append(('saveAndReloadDB', 'Save and reload current',
            self.saveAndReloadDB))
        buttons.append(('switchScan', 'Show original', self.switchScan))
        buttons.append(('unlockPreviousAccounting', 'Unlock Boxes',
            self.unlockBoxesFromPreviousAccounting))
        self.addButtonFrame(buttons)

    def nextProductToSanitize(self):
        # assuming each product is stored in productPath as a triple of
        # {productName}_{sheet}.csv,
        # {productName}_{sheet}_{originalScanPostfix},
        # {productName}_{sheet}_{normalizedScanPostfix}
        csvFiles = None
        for (_, _, filenames) in os.walk(self.productPath):
            csvFiles = sorted(filter(lambda f: os.path.splitext(f)[1] ==
                '.csv', filenames))
            originalScanFiles = sorted(filter(lambda f: f.find(self.originalScanPostfix)
                != -1, filenames))
            normalizedScanFiles = sorted(filter(lambda f: f.find(self.normalizedScanPostfix)
                != -1, filenames))
            break

        if not csvFiles:
            raise StopIteration

        foundProductToSanitize = False
        for csvFile in csvFiles:
            originalScanFile = csvFile + self.originalScanPostfix
            normalizedScanFile = csvFile + self.normalizedScanPostfix
            if originalScanFile not in originalScanFiles:
                self.log.warn(f'{csvFile} omitted, {originalScanFile} is missing')
                continue
            if normalizedScanFile not in normalizedScanFiles:
                self.log.warn(f'{csvFile} omitted, {normalizedScanFile} is missing')
                continue

            # check if this csv needs sanitation
            sheet = ProductSheet()
            sheet.load(self.productPath + csvFile)
            if list(filter(lambda box: box.confidence < 1,
                sheet.boxes())):
                foundProductToSanitize = True
                yield self.productPath + csvFile

        if foundProductToSanitize:
            # start a new round, as there are still files to sanitize
            for p in self.nextProductToSanitize():
                yield p

    def saveAndContinue(self, event=None):
        self.save()
        try:
            self.csvPath = next(self.productToSanitizeGenerator)
        except StopIteration:
            if self.numCorrectValidatedBoxes == self.numValidatedValidatedBoxes:
                messagebox.showinfo('Sanitation complete',
                    'Congratulations, your work is done')
            else:
                messagebox.showwarning('Sanitation complete',
                    """
                    Your work is done, but OCR didn't work properly.
                    Only {} out of {} validated texts were correct. Apparently OCR
                    was overconfident and probably some of the initially green
                    boxes contain wrong entries. Please check them and file a
                    bug report at https://github.com/greuters/tagtrail.git/
                    """.format(self.numCorrectValidatedBoxes, self.numValidatedValidatedBoxes))
            self.root.destroy()
        else:
            self.populateRoot()
            return "break"

    def saveAndReloadDB(self, event=None):
        self.save()
        self.db = Database(f'{self.accountingDataPath}0_input/')
        self.populateRoot()
        return "break"

    def save(self):
        if not self.inputSheet.name:
            raise ValueError('Unable to store sheet, name is missing')
        if not self.inputSheet.amountAndUnit:
            raise ValueError('Unable to store sheet, amountAndUnit is missing')
        if not self.inputSheet.grossSalesPrice:
            raise ValueError('Unable to store sheet, grossSalesPrice is missing')
        if not self.inputSheet.sheetNumber:
            raise ValueError('Unable to store sheet, sheetNumber is missing')
        oldCsvPath = self.csvPath
        oldOriginalScanPath = f'{oldCsvPath}{self.originalScanPostfix}'
        oldNormalizedScanPath = f'{oldCsvPath}{self.normalizedScanPostfix}'
        newCsvPath = f'{self.productPath}{self.inputSheet.filename}'
        newOriginalScanPath = f'{newCsvPath}{self.originalScanPostfix}'
        newNormalizedScanPath = f'{newCsvPath}{self.normalizedScanPostfix}'
        if newCsvPath != oldCsvPath:
            if os.path.exists(newCsvPath):
                raise ValueError(f'Unable to store sheet, file {newCsvPath} already exists')
            if os.path.exists(newOriginalScanPath):
                raise ValueError(f'Unable to store sheet, file {newOriginalScanPath} already exists')
            if os.path.exists(newNormalizedScanPath):
                raise ValueError(f'Unable to store sheet, file {newNormalizedScanPath} already exists')

        assert(self.inputSheet.productId() in self.db.products.keys())
        assert(not [b for b in self.inputSheet.dataBoxes()
                if b.text != '' and not b.text in self.db.members and not
                b.copiedFromPreviousAccounting])

        numCorrect, numValidated = self.inputSheet.getValidationScore()
        self.numCorrectValidatedBoxes += numCorrect
        self.numValidatedValidatedBoxes += numValidated
        self.log.info(f'sheet validation score: {numCorrect} ' + \
                f'out of {numValidated} validated texts were correct')
        self.log.info(f'total validation score: ' + \
                f'{self.numCorrectValidatedBoxes} out of ' + \
                f'{self.numValidatedValidatedBoxes} validated texts were correct')

        self.log.info(f'deleting {oldCsvPath}')
        os.remove(oldCsvPath)
        self.inputSheet.store(self.productPath)
        self.csvPath = newCsvPath
        self.log.debug(f'renaming {oldOriginalScanPath} to {newOriginalScanPath}')
        os.rename(oldOriginalScanPath, newOriginalScanPath)
        self.log.debug(f'renaming {oldNormalizedScanPath} to {newNormalizedScanPath}')
        os.rename(oldNormalizedScanPath, newNormalizedScanPath)

    def switchScan(self, event=None):
        if self.scannedImgPath == self.csvPath+self.normalizedScanPostfix:
            self.scannedImgPath = self.csvPath+self.originalScanPostfix
            self.buttons['switchScan']['text']='Show normalized'
        elif self.scannedImgPath == self.csvPath+self.originalScanPostfix:
            self.scannedImgPath = self.csvPath+self.normalizedScanPostfix
            self.buttons['switchScan']['text']='Show original'
        else:
            assert(false)
        self.loadScannedImg()

    def unlockBoxesFromPreviousAccounting(self, event=None):
        self.inputSheet.unlockBoxesFromPreviousAccounting()

    def loadScannedImg(self):
        self.scanCanvas.delete('all')
        img = Image.open(self.scannedImgPath)
        originalWidth, originalHeight = img.size
        scaleFactor = min(self.scanCanvas.winfo_height() / originalHeight,
                self.scanCanvas.winfo_width() / originalWidth)
        resizedImg = img.resize((int(originalWidth * scaleFactor),
                    int(originalHeight * scaleFactor)),
                    Image.BILINEAR)
        # Note: it is necessary to store the image locally for tkinter to show it
        self.scannedImg = ImageTk.PhotoImage(resizedImg)

        self.scanCanvas.create_image(0,0, anchor=tkinter.NW, image=self.scannedImg)
        self.__focusAreaImage = None
        self.__focusAreaBorderRect = None

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
    GUI(args.accountingDir)
