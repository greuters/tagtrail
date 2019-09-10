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
import re
from PIL import ImageTk,Image
from sheets import ProductSheet
from database import Database
from helpers import Log
from functools import partial

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
                        self._listBox = Listbox()
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
    def __init__(self, name, unit, price, quantity, root, aspectRatio,
            database, path):
        super().__init__(name, unit, price, quantity)
        self.load(path)

        self._box_to_widget = {}
        for box in self._boxes:
            if box.name == "nameBox":
                choices = [v._description for v in database._products.values()]
            elif box.name == "unitBox":
                choices = []
            elif box.name == "priceBox":
                choices = []
            elif box.name.find("dataBox") != -1:
                choices = database._members.keys()
            else:
                continue

            (x1, y1) = box.pt1
            x1, y1 = x1*aspectRatio, y1*aspectRatio
            (x2, y2) = box.pt2
            x2, y2 = x2*aspectRatio, y2*aspectRatio
            entry = AutocompleteEntry(box, choices, self.switchFocus, root)
            entry.place(x=x1, y=y1, w=x2-x1, h=y2-y1)
            self._box_to_widget[box] = entry
        self._box_to_widget[self._boxes[1]].focus_set()

    def switchFocus(self, event):
        # cudos to https://www.daniweb.com/programming/software-development/code/216830/tkinter-keypress-event-python
        if str(event.type) == "KeyPress" and event.char != event.keysym:
            # punctuation or special key, distinguish by event.keysym
            if event.keysym in ["Return", "Tab"]:
                if event.keysym == "Return":
                    event.widget.confidence=1

                nextBox = self.nextUnclearBox(event.widget.box)
                if not nextBox:
                    # TODO go to next sheet button
                    print("TODO")
                else:
                    self._box_to_widget[nextBox].focus_set()

            elif event.keysym in ["Up", "Down", "Left", "Right"]:
                neighbourBox = self.neighbourBox(event.widget.box, event.keysym)
                if neighbourBox:
                    self._box_to_widget[neighbourBox].focus_set()

        return event

    def nextUnclearBox(self, selectedBox):
        indicesOfUnclearBoxes = [idx for idx, b in enumerate(self._boxes) if b.confidence<1]
        if not indicesOfUnclearBoxes:
            return None
        else:
            currentIndex = self._boxes.index(selectedBox)
            if max(indicesOfUnclearBoxes) <= currentIndex:
                return self._boxes[min(indicesOfUnclearBoxes)]
            else:
                return self._boxes[min(filter(lambda x: currentIndex < x,
                    indicesOfUnclearBoxes))]

class MainGui:
    def __init__(self, scanPath, ocrOutputPath, memberFilePath, productFilePath):
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

        self.scannedImg = Image.open(scanPath)
        o_w, o_h = self.scannedImg.size
        aspectRatio = min(self.height / o_h, (self.width - self.buttonCanvasWidth) / 2 / o_w)
        canvas_w, canvas_h = int(o_w * aspectRatio), int(o_h * aspectRatio)
        self.scanCanvas = Canvas(self.root,
               width=canvas_w,
               height=canvas_h)
        self.scanCanvas.place(x=0, y=0)
        self.scannedImg = self.scannedImg.resize((canvas_w, canvas_h), Image.BILINEAR)
        self.scannedImg = ImageTk.PhotoImage(self.scannedImg)
        self.scanCanvas.create_image(0,0, anchor=NW, image=self.scannedImg)
        self.__focusAreaImage = None
        self.__focusAreaBorderRect = None

        self.inputCanvas = Canvas(self.root,
               width=canvas_w,
               height=canvas_h)
        self.inputCanvas.place(x=canvas_w, y=0)
        self.db = Database(memberFilePath, productFilePath)
        self.inputSheet = InputSheet("not", "known", "yet", ProductSheet.maxQuantity(),
                self.inputCanvas, aspectRatio, self.db, ocrOutputPath)

        self.buttonCanvas = Frame(self.root,
               width=self.buttonCanvasWidth,
               height=canvas_h)
        self.buttonCanvas.place(x=2*canvas_w, y=0)
        buttons = []
        buttons.append(Button(self.buttonCanvas, text='Save and next',
            command=partial(self.inputSheet.store, 'data/ocr_out/')))
        buttons.append(Button(self.buttonCanvas, text="Don't ever try this one",
            command=partial(self.inputSheet.store, 'data/ocr_out/')))

        y = 60
        for b in buttons:
            b.place(relx=.5, y=y, anchor="center",
                    width=.8*self.buttonCanvasWidth)
            b.update()
            y += b.winfo_height()

    def switchInputFocus(self, event):
        focused = self.root.focus_displayof()
        if focused and isinstance(focused, AutocompleteEntry):
            info = focused.place_info()
            self.setFocusAreaOnScan(int(info['x']), int(info['y']),
                    int(info['width']), int(info['height']))
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
    productName = 'DRINK HAFER'
    gui = MainGui('data/ocr_out/{}_normalized_scan.jpg'.format(productName),
            'data/ocr_out/{}.csv'.format(productName),
            dataFilePath.format('mitglieder.csv'),
            dataFilePath.format('produkte.csv'))

    gui.root.mainloop()
