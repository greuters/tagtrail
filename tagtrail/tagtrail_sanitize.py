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
    """
    InputSheet provides the user a GUI representation to fill in tags of a
    ProductSheet.

    Each box is associated with a
    :class:`tagtrail.gui_components.AutocompleteEntry` to input data. As soon
    as name and sheet number are filled in, existing tags are loaded from the
    last accounting if the corresponding sheet exists in 0_input/sheets, and
    the loaded boxes are locked s.t. the user can only enter and correct new
    tags, while leaving the already accounted ones alone.

    As a quality control of tagtrail_ocr, a number of boxes with high
    confidence are validated on each sheet. If an input sheet exists, all tags
    that already existed in the input are used to validate the corresponding
    tags suggested by tagtrail_ocr (no burden on user). If not enough tags
    could be validated this way, some of the confident boxes are randomly
    selected and presented to the user as unclear to get an independent
    validation source.

    :cvar numBoxesToValidate: minimal number of tags per sheet to validate
    """
    numBoxesToValidate = 2
    maxEpectedListboxHeight = 200

    def __init__(self, parentFrame, db, sheetPath, inputSheetsDir):
        """
        :param parentFrame: tkinter widget to add the autocomplete entries to
        :type parentFrame: :class:`tkinter.frame`
        :param db: db to load possible values for each box from
        :type db: :class:`tagtrail.database.Database`
        :param sheetPath: path to load the sheet from
        :type sheetPath: str
        :param inputSheetsDir: path to previously accounted sheets
        :type inputSheetsDir: str
        """
        super().__init__(log=Log())
        self.db = db
        self.load(sheetPath)
        self.originalPath = sheetPath
        self.inputSheetsDir = inputSheetsDir
        self.__createWidgets(parentFrame)
        self.__manualValidationBoxNames = self.__selectManualValidationBoxes()

        self.__loadTagsFromPreviousAccounting()
        self.__ensureEnoughValidationBoxes()
        nextUnclearBox = self.nextUnclearBox(None)
        if nextUnclearBox:
            nextUnclearBox.entry.focus_set()

    def __createWidgets(self, parentFrame):
        """
        Create a :class:`tagtrail.gui_components.AutocompleteEntry` for each
        box and add them to parentFrame

        Possible values to enter into each entry are loaded from self.db.

        :param parentFrame: tkinter widget to add the autocomplete entries to
        :type parentFrame: :class:`tkinter.frame`
        :param database: database to load possible values for each box from
        :type database: :class:`tagtrail.database.Database`
        """
        # prepare choices
        maxNumSheets = self.db.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')
        sheetNumberString = self.db.config.get('tagtrail_gen',
                'sheet_number_string')
        sheetNumbers = [sheetNumberString.format(sheetNumber=str(n))
                            for n in range(1, maxNumSheets+1)]
        currency = self.db.config.get('general', 'currency')
        names, units, prices = map(set, zip(*[
            (p.description,
             p.amountAndUnit,
             formatPrice(p.grossSalesPrice(), currency))
            for p in self.db.products.values()]))

        scaleFactor = min(parentFrame.winfo_height() / self.yRes,
                parentFrame.winfo_width() / self.xRes)

        # Each box with OCR data gets an associated AutocompleteEntry widget.
        # These entries are initialised with the same tags and confidences as
        # their owner boxes, but can be corrected by user input or from a
        # previous, already sanitized, version of the sheet.
        #
        # The new tags are only written to the owner boxes in self.store(),
        # after checking all entries are validated (confidence == 1).
        #
        # Keeping the originally loaded tags and confidences stored in the
        # owner boxes apart from the corected input in the entries enables us
        # to validate the precision of the original tags by letting the user
        # correct a few entries where the owner box actually has a
        # confidence == 1 and should therefore contain the correct tag already.
        for box in self.boxes():
            if box.name == "nameBox":
                choices = names
            elif box.name == "unitBox":
                choices = units
            elif box.name == "priceBox":
                choices = prices
            elif box.name == "sheetNumberBox":
                choices = sheetNumbers
            elif box.name.find("dataBox") != -1:
                choices = list(sorted(self.db.members.keys()))
            else:
                box.entry = None
                continue

            (x1, y1) = box.pt1
            x1, y1 = x1*scaleFactor, y1*scaleFactor
            (x2, y2) = box.pt2
            x2, y2 = x2*scaleFactor, y2*scaleFactor
            listBoxY = y2
            if listBoxY + self.maxEpectedListboxHeight > parentFrame.winfo_height():
                listBoxY = y1 - self.maxEpectedListboxHeight

            entry = gui_components.AutocompleteEntry(box.text, box.confidence,
                    choices, self.releaseFocus, True, parentFrame, x1,
                    listBoxY, parentFrame)
            entry.place(x=x1, y=y1, w=x2-x1, h=y2-y1)
            entry.copiedFromPreviousAccounting = False
            entry.manuallyValidated = False
            entry.box = box
            box.entry = entry

    def __selectManualValidationBoxes(self):
        """
        Select boxes to validate manually if not enough boxes can be validated
        automatically from the previously accounted corresponding input sheet.

        To control quality of automatically recognized tags, a certain number
        of boxes should be verified in each sheet. From all boxes with
        high confidence (tagtrail_ocr claimed to know the correct tag), a
        random sample is taken which has to be manually tagged again by the
        user, if not enough boxes can be validated automatically.

        :return: list of box.name to validate manually if necessary
        :rtype: list of str
        """
        candidateValidationBoxes = [box.name for box in self.dataBoxes()
                if box.confidence == 1 and box.entry is not None]
        selected = random.sample(candidateValidationBoxes,
                min(self.numBoxesToValidate, len(candidateValidationBoxes)))
        self._log.debug(f'selected manualValidationBoxes: {selected}')
        return selected

    def __ensureEnoughValidationBoxes(self):
        """
        Check how many boxes can be validated automatically and, if necessary,
        clear enough of self.__manualValidationBoxes to guarantee adequate
        quality control.
        """
        numAutomaticallyValidatedBoxes = 0
        for box in self.boxes():
            if box.entry is None:
                continue

            if (box.confidence == 1 and
                    box.entry.copiedFromPreviousAccounting):
                numAutomaticallyValidatedBoxes += 1
                self._log.debug(f'{box.name} can be validated automatically')

        self._log.debug('numAutomaticallyValidatedBoxes = '
                f'{numAutomaticallyValidatedBoxes}')
        numRemaining = max(0,
                self.numBoxesToValidate-numAutomaticallyValidatedBoxes)
        for name in self.__manualValidationBoxNames:
            box = self._boxes[name]
            if box.entry is None:
                continue

            if box.entry.copiedFromPreviousAccounting:
                # cannot use this box again, as it was already counted in the
                # automatically validated boxes
                box.entry.manuallyValidated = False

            elif numRemaining == 0:
                # no more manual validation necessary
                box.entry.enabled = True
                box.entry.text = box.text
                box.entry.confidence = box.confidence
                box.entry.manuallyValidated = False

            else:
                # reset this box and let the user fill it in
                self._log.debug(
                        f'{name} has to be validated manually')
                box.entry.manuallyValidated = True
                box.entry.enabled = True
                box.entry.setArbitraryText('')
                box.entry.confidence = 0
                box.entry.destroyListBox()

                numRemaining -= 1

        assert(numRemaining <= self.numBoxesToValidate -
                len(self.__manualValidationBoxNames))

    def __updatedProductId(self):
        return slugify.slugify(self._boxes['nameBox'].entry.text)

    def __updatedSheetNumber(self):
        return self._boxes['sheetNumberBox'].entry.text

    @property
    def updatedFilename(self):
        """
        Filename of the sheet if it was stored with currently entered
        information in the GUI
        input
        """
        return f'{self.__updatedProductId()}_{self.__updatedSheetNumber()}.csv'

    def __loadTagsFromPreviousAccounting(self):
        """
        Load tags from last accounting if name and sheetNumber of this sheet
        are clear and the sheet already existed.
        """
        if self._boxes['nameBox'].entry.confidence != 1:
            return
        if  self._boxes['sheetNumberBox'].entry.confidence != 1:
            return

        sheetName = '{}_{}.csv'.format(self.__updatedProductId(),
                self.__updatedSheetNumber())
        activeSheetPath = f'{self.inputSheetsDir}/active/{sheetName}'
        inactiveSheetPath = f'{self.inputSheetsDir}/inactive/{sheetName}'
        if os.path.exists(activeSheetPath):
            self.__loadTagsFromAccountedSheet(activeSheetPath)
        elif os.path.exists(inactiveSheetPath):
            self.__loadTagsFromAccountedSheet(inactiveSheetPath)

    def __loadTagsFromAccountedSheet(self, sheetPath):
        """
        Load tags from specified accounted sheet.

        Entries with tags from accounted sheet are locked, as they have already
        been accounted and should not be changed any more. All other entry
        widgets are unlocked.

        :param sheetPath: path to the accounted sheet
        :type sheetPath: str
        :raises ValueError: if accounted sheet has boxes with unconfident tags
            or isn't the same sheet as self (productId or sheetNumber don't
            match)
        """
        self._log.debug(f'loading previous tags from {sheetPath}')

        accountedSheet = ProductSheet()
        accountedSheet.load(sheetPath)
        if accountedSheet.productId() != self.__updatedProductId():
            raise ValueError(f'{sheetPath} has wrong productId '
                    f'({accountedSheet.productId()} != '
                    f'{self.__updatedProductId()})')
        if accountedSheet.sheetNumber != self.__updatedSheetNumber():
            raise ValueError(f'{sheetPath} has wrong sheetNumber '
                f'({accountedSheet.sheetNumber} != '
                f'{self.__updatedSheetNumber()})')
        if [box for box in accountedSheet.boxes()
                if box.confidence != 1.0]:
            raise ValueError(
                    f'{sheetPath} has boxes with confidence != 1')

        for accountedBox in accountedSheet.boxes():
            box = self._boxes[accountedBox.name]
            if box.entry is None:
                continue

            if accountedBox.text == '':
                self._log.debug(f'resetting box {accountedBox.name}')
                if (box.entry.text != '' and
                        box.entry.text not in box.entry.possibleValues):
                    # entry had been set to some now invalid value from another
                    # accountedSheet -> clear
                    assert(box.entry.copiedFromPreviousAccounting)
                    box.entry.enabled = False
                    box.entry.setArbitraryText('')
                if box.entry.copiedFromPreviousAccounting:
                    # entry had been set from another accountedSheet ->
                    # probably tag was incorrect if we're switching the
                    # accountedSheet now
                    box.entry.confidence = 0
                box.entry.copiedFromPreviousAccounting = False
                box.entry.enabled = True
            else:
                self._log.debug('copying tag from previous accounting '
                        f'{accountedBox.name}: {accountedBox.text}')
                box.entry.copiedFromPreviousAccounting = True
                box.entry.enabled = False
                box.entry.setArbitraryText(accountedBox.text)
                box.entry.confidence = 1

            box.entry.destroyListBox()

    def unlockBoxesFromPreviousAccounting(self):
        for box in self.boxes():
            if box.entry.copiedFromPreviousAccounting:
                box.entry.confidence = 0
                box.entry.copiedFromPreviousAccounting = False
                if box.entry.text not in box.entry.possibleValues:
                    box.entry.setArbitraryText('')
                box.entry.enabled = True

    def releaseFocus(self, event):
        # cudos to https://www.daniweb.com/programming/software-development/code/216830/tkinter-keypress-event-python
        if str(event.type) == "KeyPress" and event.char != event.keysym:
            # punctuation or special key, distinguish by event.keysym
            if event.keysym == "Return":
                event.widget.confidence = 1
                event.widget.manuallyValidated = True
            if event.widget.enabled:
                if event.widget.box.name in ['nameBox', 'sheetNumberBox']:
                    self.__loadTagsFromPreviousAccounting()
                    self.__ensureEnoughValidationBoxes()

            shift_pressed = (event.state & 0x1)
            if event.keysym == 'Return' and shift_pressed:
                # keep focus on current box, this is only used to confirm the
                # current selection
                return 'break'

            elif event.keysym in ["Tab", 'Return']:
                nextBox = self.nextUnclearBox(event.widget.box)
                if nextBox and event.state != 'Shift':
                    nextBox.entry.focus_set()

            elif event.keysym in ["Up", "Down", "Left", "Right"]:
                neighbourBox = self.neighbourBox(event.widget.box, event.keysym)
                if neighbourBox:
                    neighbourBox.entry.focus_set()

        return event

    def nextUnclearBox(self, selectedBox):
        if self._boxes['nameBox'].entry.confidence != 1:
            return self._boxes['nameBox']
        if  self._boxes['sheetNumberBox'].entry.confidence != 1:
            return self._boxes['sheetNumberBox']
        sortedBoxes = self.sortedBoxes()
        indicesOfUnclearBoxes = [idx for idx, b in enumerate(sortedBoxes) if
                b.entry is not None and b.entry.confidence<1]
        if not indicesOfUnclearBoxes:
            return None
        else:
            currentIndex = (0 if selectedBox is None else
                    sortedBoxes.index(selectedBox))
            if max(indicesOfUnclearBoxes) <= currentIndex:
                return sortedBoxes[min(indicesOfUnclearBoxes)]
            else:
                return sortedBoxes[min(filter(lambda x: currentIndex < x,
                    indicesOfUnclearBoxes))]

    def getValidationScore(self):
        """
        Compare the originally loaded confident tags with the validated input

        Precondition: input has to be fully validated, i.e.
            for box in self.boxes():
                if box.entry is None:
                    assert(box.entry.confidence == 1)
        and to get useful output, store() must not yet have been called.

        :return: (numCorrect, numValidated), where numCorrect is the number of
            validated boxes which were correctly tagged in the originally
            loaded sheet and numValidated the total number of boxes validated
        :rtype: (int, int)
        :raises AssertionError: if this sheet is not fully validated
        """
        unconfidentBoxes = [box.name for box in self.boxes()
                if box.entry is not None and box.entry.confidence != 1]
        if unconfidentBoxes != []:
            raise AssertionError(
                    f'Precondition violated by following boxes {unconfidentBoxes}')

        numCorrect = 0
        numValidated = 0
        for box in self.boxes():
            if box.confidence != 1 or box.entry is None:
                continue

            if (box.entry.copiedFromPreviousAccounting or
                    box.entry.manuallyValidated):
                numValidated += 1
                if box.text == box.entry.text:
                    numCorrect += 1
                else:
                    self._log.info(f'{box.name} was incorrectly tagged '
                            f"'{box.text}' instead of '{box.entry.text}'")
        assert(numValidated >= len(self.__manualValidationBoxNames))
        return (numCorrect, numValidated)

    def store(self, sheetDir):
        """
        Write user input through to sheet boxes and store the sheet to disk

        Up to this point, all user input is only stored in the associated
        autocomplete entry of each box, while the boxes still contain the
        original tags loaded from file.
        After this call, the input is stored in this sheets boxes.

        :param sheetDir: directory to store the sheet to
        :type sheetDir: str
        :raises ValueError: if mandatory boxes (name, amountAndUnit,
            grossSalesPrice, sheetNumber) are not filled in or any box has
            confidence != 1
        """
        unconfidentBoxes = [box.name for box in self.boxes()
                if box.entry is not None and box.entry.confidence != 1]
        if unconfidentBoxes != []:
            raise ValueError(
                    f'Unable to store sheet, unclear boxes {unconfidentBoxes}')
        if not self._boxes['nameBox'].entry.text:
            raise ValueError('Unable to store sheet, name is missing')
        if not self._boxes['unitBox'].entry.text:
            raise ValueError('Unable to store sheet, amountAndUnit is missing')
        if not self._boxes['priceBox'].entry.text:
            raise ValueError('Unable to store sheet, grossSalesPrice is missing')
        if not self._boxes['sheetNumberBox'].entry.text:
            raise ValueError('Unable to store sheet, sheetNumber is missing')

        for box in self.boxes():
            if box.entry is None:
                continue
            box.text = box.entry.text
            box.confidence = box.entry.confidence

        assert(self.productId() in self.db.products.keys())
        assert(not [b for b in self.dataBoxes()
                if b.text != ''
                and not b.text in self.db.members
                and not b.entry.copiedFromPreviousAccounting])

        super().store(sheetDir)

class GUI(gui_components.BaseGUI):
    originalScanPostfix = '_original_scan.jpg'
    normalizedScanPostfix = '_normalized_scan.jpg'
    minAveragePrecision = 0.98

    def __init__(self, accountingDataPath, log = Log(Log.LEVEL_INFO)):
        self.accountingDataPath = accountingDataPath
        self.productPath = f'{self.accountingDataPath}2_taggedProductSheets/'
        self.sheetsPath = f'{self.accountingDataPath}0_input/sheets/'
        self.db = Database(f'{self.accountingDataPath}0_input/')
        self.numCorrectValidatedBoxes = 0
        self.numValidatedBoxesoxes = 0
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
        self.log.info('')
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
        if focused and hasattr(focused, 'place_info'):
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
        if not self.save():
            return

        try:
            self.csvPath = next(self.productToSanitizeGenerator)
        except StopIteration:
            precision = self.numCorrectValidatedBoxes / self.numValidatedBoxesoxes
            if precision > self.minAveragePrecision:
                messagebox.showinfo('Sanitation complete',
                    'Congratulations, your work is done')
            else:
                messagebox.showwarning('Sanitation complete',
                    """
                    Your work is done, but OCR quality was poor.
                    Only {} out of {} validated texts were correct, indicating
                    tagtrail_ocr was overconfident and it can be expected that
                    {:.0f}% of the initially green boxes contain wrong tags.

                    Consider to abort accounting here and redo the scans if
                    this is not good enough for you.

                    Please check the quality of your input scans and file a
                    bug report at https://github.com/greuters/tagtrail.git/ if
                    you think they are comparable to those in
                    tests/data/template_medium/0_input/scans/
                    """.format(self.numCorrectValidatedBoxes,
                        self.numValidatedBoxesoxes, (1-precision) * 100))
            self.root.destroy()
        else:
            self.populateRoot()
            return "break"

    def saveAndReloadDB(self, event=None):
        if self.save():
            self.db = Database(f'{self.accountingDataPath}0_input/')
            self.populateRoot()
            return "break"

    def save(self):
        """
        Save the current input sheet.

        :return: True if all worked. False if validation score of the sheet is
            too low and the user canceled the operation.
        :rtype: bool
        """
        oldCsvPath = self.csvPath
        oldOriginalScanPath = f'{oldCsvPath}{self.originalScanPostfix}'
        oldNormalizedScanPath = f'{oldCsvPath}{self.normalizedScanPostfix}'
        newCsvPath = f'{self.productPath}{self.inputSheet.updatedFilename}'
        newOriginalScanPath = f'{newCsvPath}{self.originalScanPostfix}'
        newNormalizedScanPath = f'{newCsvPath}{self.normalizedScanPostfix}'
        if newCsvPath != oldCsvPath:
            if os.path.exists(newCsvPath):
                raise ValueError(f'Unable to store sheet, file {newCsvPath} already exists')
            if os.path.exists(newOriginalScanPath):
                raise ValueError(f'Unable to store sheet, file {newOriginalScanPath} already exists')
            if os.path.exists(newNormalizedScanPath):
                raise ValueError(f'Unable to store sheet, file {newNormalizedScanPath} already exists')

        numCorrect, numValidated = self.inputSheet.getValidationScore()
        if numCorrect != numValidated:
            answer = messagebox.askokcancel('Bad initial tags',
                    f'Only {numCorrect} out of {numValidated} validated tags '
                    'were correct.\n'
                    'Please check tags again (especially the initially green '
                    'boxes) and cancel storage if you need to edit again.',
                    default = messagebox.CANCEL)
            if answer == False:
                return False

        self.numCorrectValidatedBoxes += numCorrect
        self.numValidatedBoxesoxes += numValidated
        self.log.info(f'sheet validation score: {numCorrect} ' + \
                f'out of {numValidated} validated texts were correct')
        self.log.info(f'total validation score: ' + \
                f'{self.numCorrectValidatedBoxes} out of ' + \
                f'{self.numValidatedBoxesoxes} validated texts were correct')

        self.inputSheet.store(self.productPath)
        if oldCsvPath != newCsvPath:
            self.log.info(f'deleting {oldCsvPath}')
            os.remove(oldCsvPath)
        self.csvPath = newCsvPath
        self.log.debug(f'renaming {oldOriginalScanPath} to {newOriginalScanPath}')
        os.rename(oldOriginalScanPath, newOriginalScanPath)
        self.log.debug(f'renaming {oldNormalizedScanPath} to {newNormalizedScanPath}')
        os.rename(oldNormalizedScanPath, newNormalizedScanPath)
        return True

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
