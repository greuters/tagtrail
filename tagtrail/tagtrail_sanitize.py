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
    def __init__(self, name, unit, price, quantity, database, path):
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
            x1, y1 = x1*ratio, y1*ratio
            (x2, y2) = box.pt2
            x2, y2 = x2*ratio, y2*ratio
            entry = AutocompleteEntry(box, choices, self.switchFocus, root)
            entry.place(x=canvas_w+x1, y=y1, w=x2-x1, h=y2-y1)
            self._box_to_widget[box] = entry

    def switchFocus(self, event):
        if str(event.type) != "KeyPress":
            return event

        # cudos to https://www.daniweb.com/programming/software-development/code/216830/tkinter-keypress-event-python
        if event.char == event.keysym:
            # normal key, not handled here
            return event
        else:
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
                    # TODO switch highlight on canvas as well

                return "break"

            elif event.keysym in ["Up", "Down", "Left", "Right"]:
                neighbourBox = self.neighbourBox(event.widget.box, event.keysym)
                if neighbourBox:
                    self._box_to_widget[neighbourBox].focus_set()
                return "break"
            else:
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

# TODO: refactor
images = []  # to hold the newly created image

def create_rectangle(x1, y1, x2, y2, **kwargs):
    if 'alpha' in kwargs:
        alpha = int(kwargs.pop('alpha') * 255)
        fill = kwargs.pop('fill')
        fill = root.winfo_rgb(fill) + (alpha,)
        image = Image.new('RGBA', (x2-x1, y2-y1), fill)
        images.append(ImageTk.PhotoImage(image))
        canvas.create_image(x1, y1, image=images[-1], anchor='nw')
    canvas.create_rectangle(x1, y1, x2, y2, **kwargs)


if __name__ == '__main__':
    root = Tk()
    window_w, window_h = 1366, 768
    root.geometry(str(window_w)+'x'+str(window_h))

    canvas_w, canvas_h = window_w/2, window_h
    canvas = Canvas(root,
               width=canvas_w,
               height=canvas_h)
    canvas.place(x=0, y=0)
    img = Image.open("data/scans/test0002.jpg")
    o_w, o_h = img.size
    ratio = min(canvas_h / o_h, canvas_w / o_w)
    img = img.resize((int(ratio * o_w), int(ratio * o_h)), Image.BILINEAR)
    img = ImageTk.PhotoImage(img)
    canvas.create_image(0,0, anchor=NW, image=img)
    create_rectangle(10, 10, 200, 100, fill='green', alpha=0.2)

    dataFilePath = 'data/database/{}'
    db = Database(dataFilePath.format('mitglieder.csv'),
            dataFilePath.format('produkte.csv'))
    sheet = InputSheet("not", "known", "yet",
            ProductSheet.maxQuantity(), db, 'data/ocr_out/DRINK HAFER.csv')

    root.mainloop()
