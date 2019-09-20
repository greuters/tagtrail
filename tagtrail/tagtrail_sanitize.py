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
from tkinter import *
from tkinter import ttk
from tkinter import messagebox
import re
import os
from PIL import ImageTk,Image
from sheets import ProductSheet
from database import Database
from helpers import Log
from functools import partial
import random

class AutocompleteEntry(ttk.Combobox):
    def __init__(self, box, possibleValues, releaseFocus, *args, **kwargs):
        Entry.__init__(self, *args, **kwargs)
        self.box = box
        self._possibleValues = possibleValues
        self._releaseFocus = releaseFocus
        self._log = Log()
        self._previousValue = ""
        self._listBox = None
        self.__var = self["textvariable"]
        if self.__var == '':
            self.__var = self["textvariable"] = StringVar()

        # setting text, but avoid loosing initial confidence
        initConfidence = box.confidence
        self.text = box.text
        self.confidence = initConfidence

        self.__var.trace('w', self.varTextChanged)
        self.bind("<Return>", self.selection)
        self.bind("<Up>", self.up)
        self.bind("<Down>", self.down)
        self.bind("<Left>", self.handleReleaseFocus)
        self.bind("<Right>", self.handleReleaseFocus)
        self.bind("<BackSpace>", self.backspace)
        self.bind("<Tab>", self.handleReleaseFocus)

    def up(self, event):
        if self._listBox:
            self.changeListBoxSelection(-1)
        else:
            return self._releaseFocus(event)

    def down(self, event):
        if self._listBox:
            self.changeListBoxSelection(1)
        else:
            return self._releaseFocus(event)

    def handleReleaseFocus(self, event):
        if self._listBox:
            return "break"
        else:
            return self._releaseFocus(event)

    def selection(self, event):
        if self._listBox:
            self.text = self._listBox.get(ACTIVE)
            self.box.text = self.text
            self.icursor(END)
            self.destroyListBox()
        return self._releaseFocus(event)

    def varTextChanged(self, name, index, mode):
        self._log.debug('changed var = {}', self.text)
        self.confidence = 0
        if self.text == '':
            self.destroyListBox()
        else:
            words = self.comparison(self.text)
            self._log.debug('possible words = {}', words)
            if not words:
                self.text = self._previousValue
            else:
                longestCommonPrefix = self.longestCommonPrefix(words)
                self._log.debug('longestCommonPrefix(words) = {}', self.longestCommonPrefix(words))
                if longestCommonPrefix != self.text.upper():
                    self.delete(0, END)
                    self.insert(0, longestCommonPrefix)

                if len(words) == 1:
                        self.destroyListBox()

                else:
                    if not self._listBox:
                        self._listBox = Listbox(self.master)
                        self._listBox.place(x=self.winfo_x(), y=self.winfo_y()+self.winfo_height())

                    self._listBox.delete(0, END)
                    for w in words:
                        self._listBox.insert(END,w)

        self._previousValue = self.text

    def backspace(self, event):
        if self.text == '':
            self.destroyListBox()
        else:
            word = self.text
            numOptions = len(self.comparison(word))
            prefixes = [word[0:i] for i in range(len(word)+1)]
            for p in sorted(prefixes, reverse=True):
                if len(p) == 0 or numOptions < len(self.comparison(p)):
                    self.text = p
                    break
        return "break"

    def focus_set(self):
        super().focus_set()
        self.icursor(END)

    # precondition: _listBox exists
    def changeListBoxSelection(self, indexIncrement):
        if self._listBox.curselection() == ():
            previousIndex = 0
        else:
            previousIndex = int(self._listBox.curselection()[0])
        newIndex = min(max(previousIndex+indexIncrement, 0),
                self._listBox.size()-1)

        self._listBox.selection_clear(first=previousIndex)
        self._listBox.selection_set(first=newIndex)
        self._listBox.activate(newIndex)

    def destroyListBox(self):
        if self._listBox:
            self._listBox.destroy()
            self._listBox = None

    def longestCommonPrefix(self, words):
        word = words[0].upper()
        prefixes = [word[0:i] for i in range(len(word)+1)]
        for p in sorted(prefixes, reverse=True):
            isPrefix = [(w.upper().find(p) == 0) for w in words]
            if len(p) == 0 or False not in isPrefix:
                return p

    def comparison(self, word):
        if not self._possibleValues:
            return [word]
        return [w for w in self._possibleValues if w.upper().find(word.upper()) == 0]

    @property
    def text(self):
        return self.__var.get()

    @text.setter
    def text(self, text):
        self.__var.set(text)

    @property
    def confidence(self):
        return self.box.confidence

    @confidence.setter
    def confidence(self, confidence):
        self.box.confidence = confidence
        if confidence < 1:
            self.config({"background": 'red'})
        else:
            self.config({"background": 'green'})

class InputSheet(ProductSheet):
    validationProbability = 0.05

    def __init__(self, name, unit, price, quantity, root, aspectRatio,
            database, path):
        super().__init__(name, unit, price, 0, quantity)
        self.load(path)
        self.originalPath = path

        self._box_to_widget = {}
        self.validationBoxTexts = {}
        for box in self._boxes.values():
            if box.name == "nameBox":
                choices = [v._description for v in database._products.values()]
            elif box.name == "unitBox":
                choices = []
            elif box.name == "priceBox":
                choices = []
            elif box.name == "pageNumberBox":
                choices = [str(x) for x in range(100)]
            elif box.name.find("dataBox") != -1:
                choices = database._members.keys()
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
            entry = AutocompleteEntry(box, choices, self.switchFocus, root)
            entry.place(x=x1, y=y1, w=x2-x1, h=y2-y1)
            self._box_to_widget[box] = entry

        self._box_to_widget[self._boxes['nameBox']].focus_set()

    def switchFocus(self, event):
        # cudos to https://www.daniweb.com/programming/software-development/code/216830/tkinter-keypress-event-python
        if str(event.type) == "KeyPress" and event.char != event.keysym:
            # punctuation or special key, distinguish by event.keysym
            if event.keysym in ["Return", "Tab"]:
                if event.keysym == "Return":
                    event.widget.confidence=1

                nextBox = self.nextUnclearBox(event.widget.box)
                if nextBox:
                    self._box_to_widget[nextBox].focus_set()

            elif event.keysym in ["Up", "Down", "Left", "Right"]:
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
        for box in self._boxes.values():
            if box.name in self.validationBoxTexts and box.confidence == 1:
                numValidated += 1
                if self.validationBoxTexts[box.name] == box.text:
                    numCorrect += 1

        return (numCorrect, numValidated)

class MainGui:
    scanPostfix = '_normalized_scan.jpg'

    def __init__(self, dataPath, memberFilePath, productFilePath):
        self.log = Log()
        self.dataPath = dataPath
        self.memberFilePath = memberFilePath
        self.productFilePath = productFilePath
        self.db = Database(self.memberFilePath, self.productFilePath)
        self.pairToSanitizeGenerator = self.nextPairToSanitize()
        self.numCorrectValidatedBoxes = 0
        self.numValidatedValidatedBoxes = 0

        self.root = Tk()
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

        try:
            self.csvPath, self.scanPath = next(self.pairToSanitizeGenerator)
        except StopIteration:
            messagebox.showinfo('Nothing to do',
                'No file needing sanitation in input path {}'.format(dataPath))
            self.root.destroy()
        else:
            self.loadProductSheet()

    def nextPairToSanitize(self):
        # assuming each product is stored in dataPath as a pair of
        # ({productName}_{page}.csv, {productName}_{page}_normalized_scan.jpg)
        for (_, _, fileNames) in os.walk(self.dataPath):
            csvFiles = sorted(filter(lambda f: os.path.splitext(f)[1] ==
                '.csv', fileNames))
            scanFiles = sorted(filter(lambda f: f.find(self.scanPostfix)
                != -1, fileNames))
            break

        foundPairToSanitize = False
        for csvFile in csvFiles:
            scanFile = os.path.splitext(csvFile)[0] + self.scanPostfix
            if scanFile in scanFiles:
                # check if this csv needs sanitation
                sheet = ProductSheet("not", "known", "yet", 0,
                        ProductSheet.maxQuantity(), self.db)
                sheet.load(self.dataPath + csvFile)
                if list(filter(lambda box: box.confidence < 1,
                    sheet._boxes.values())):
                    foundPairToSanitize = True
                    yield (self.dataPath + csvFile, self.dataPath + scanFile)
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
        self.db = Database(self.memberFilePath, self.productFilePath)
        self.loadProductSheet()
        return "break"

    def save(self):
        numCorrect, numValidated = self.inputSheet.getValidationScore()
        self.numCorrectValidatedBoxes += numCorrect
        self.numValidatedValidatedBoxes += numValidated
        self.log.info('sheet validation score: {} out of {} validated texts were correct',
                numCorrect, numValidated)
        self.log.info('total validation score: {} out of {} validated texts were correct',
                self.numCorrectValidatedBoxes, self.numValidatedValidatedBoxes)
        os.remove(self.csvPath)
        self.inputSheet.store(self.dataPath)
        os.rename(self.scanPath, "{}{}_{}{}".format(self.dataPath,
            self.inputSheet._boxes['nameBox'].text,
            self.inputSheet._boxes['pageNumberBox'].text,
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
        self.scanCanvas = Canvas(self.root,
               width=canvas_w,
               height=canvas_h)
        self.scanCanvas.place(x=0, y=0)
        self.scanCanvas.create_image(0,0, anchor=NW, image=self.scannedImg)
        self.__focusAreaImage = None
        self.__focusAreaBorderRect = None

        # Input mask to correct product sheet
        self.inputCanvas = Canvas(self.root,
               width=canvas_w,
               height=canvas_h)
        self.inputCanvas.place(x=canvas_w, y=0)
        self.inputSheet = InputSheet("not", "known", "yet", ProductSheet.maxQuantity(),
                self.inputCanvas, aspectRatio, self.db, self.csvPath)

        # Additional buttons
        self.buttonCanvas = Frame(self.root,
               width=self.buttonCanvasWidth,
               height=canvas_h)
        self.buttonCanvas.place(x=2*canvas_w, y=0)
        self.buttons = {}
        self.buttons['saveAndContinue'] = Button(self.buttonCanvas, text='Save and continue',
            command=self.saveAndContinue)
        self.buttons['saveAndContinue'].bind('<Return>', self.saveAndContinue)
        self.buttons['saveAndReloadDB'] = Button(self.buttonCanvas,
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
        elif isinstance(focused, AutocompleteEntry):
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

if __name__ == '__main__':
    dataFilePath = 'data/database/{}'
    gui = MainGui('data/ocr_out/',
            dataFilePath.format('mitglieder.csv'),
            dataFilePath.format('produkte.csv'))
    gui.root.mainloop()
