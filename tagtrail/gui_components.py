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
from tkinter import simpledialog, ttk
import tkinter
import helpers

class AutocompleteEntry(ttk.Combobox):
    def __init__(self, text, confidence, possibleValues, releaseFocus, *args, **kwargs):
        tkinter.Entry.__init__(self, *args, **kwargs)
        self.__possibleValues = possibleValues
        self.__releaseFocus = releaseFocus
        self.__log = helpers.Log()
        self.__previousValue = ""
        self.__listBox = None
        self.__var = self["textvariable"]
        if self.__var == '':
            self.__var = self["textvariable"] = tkinter.StringVar()
        self.text = text
        self.confidence = confidence

        self.__var.trace('w', self.varTextChanged)
        self.bind("<Return>", self.selection)
        self.bind("<Up>", self.up)
        self.bind("<Down>", self.down)
        self.bind("<Left>", self.handleReleaseFocus)
        self.bind("<Right>", self.handleReleaseFocus)
        self.bind("<BackSpace>", self.backspace)
        self.bind("<Tab>", self.handleReleaseFocus)

    def up(self, event):
        if self.__listBox:
            self.changeListBoxSelection(-1)
        else:
            return self.__releaseFocus(event)

    def down(self, event):
        if self.__listBox:
            self.changeListBoxSelection(1)
        else:
            return self.__releaseFocus(event)

    def handleReleaseFocus(self, event):
        if self.__listBox:
            return "break"
        else:
            return self.__releaseFocus(event)

    def selection(self, event):
        if self.__listBox:
            self.text = self.__listBox.get(tkinter.ACTIVE)
            self.confidence = 1
            self.icursor(tkinter.END)
            self.destroyListBox()
        return self.__releaseFocus(event)

    def varTextChanged(self, name, index, mode):
        self.__log.debug('changed var = {}', self.text)
        self.confidence = 0
        if self.text == '':
            self.destroyListBox()
        else:
            if self.text.strip() == '':
                words = self.__possibleValues
            else:
                words = self.comparison(self.text)
            self.__log.debug('possible words = {}', words)
            if not words:
                self.text = self.__previousValue
            else:
                longestCommonPrefix = self.longestCommonPrefix(words)
                self.__log.debug('longestCommonPrefix(words) = {}', self.longestCommonPrefix(words))
                if longestCommonPrefix != self.text.upper():
                    self.delete(0, tkinter.END)
                    self.insert(0, longestCommonPrefix)

                if len(words) == 1:
                        self.destroyListBox()

                else:
                    if not self.__listBox:
                        self.__listBox = tkinter.Listbox(self.master)
                        self.__listBox.place(x=self.winfo_x(), y=self.winfo_y()+self.winfo_height())

                    self.__listBox.delete(0, tkinter.END)
                    for w in words:
                        self.__listBox.insert(tkinter.END,w)

        self.__previousValue = self.text

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
        self.icursor(tkinter.END)

    # precondition: _listBox exists
    def changeListBoxSelection(self, indexIncrement):
        if self.__listBox.curselection() == ():
            previousIndex = 0
        else:
            previousIndex = int(self.__listBox.curselection()[0])
        newIndex = min(max(previousIndex+indexIncrement, 0),
                self.__listBox.size()-1)

        self.__listBox.selection_clear(first=previousIndex)
        self.__listBox.selection_set(first=newIndex)
        self.__listBox.activate(newIndex)

    def destroyListBox(self):
        if self.__listBox:
            self.__listBox.destroy()
            self.__listBox = None

    def longestCommonPrefix(self, words):
        word = words[0].upper()
        prefixes = [word[0:i] for i in range(len(word)+1)]
        for p in sorted(prefixes, reverse=True):
            isPrefix = [(w.upper().find(p) == 0) for w in words]
            if len(p) == 0 or False not in isPrefix:
                return p

    def comparison(self, word):
        if not self.__possibleValues:
            return [word]
        return [w for w in self.__possibleValues if w.upper().find(word.upper()) == 0]

    @property
    def text(self):
        return self.__var.get()

    @text.setter
    def text(self, text):
        self.__var.set(text)

    @property
    def confidence(self):
        return self.__confidence

    @confidence.setter
    def confidence(self, confidence):
        self.__confidence = confidence
        if confidence < 1:
            self.config({"background": 'red'})
        else:
            self.config({"background": 'green'})

class Checkbar(tkinter.Frame):
   def __init__(self, parent=None, title='', picks=[], available=True,
           numCols=5, side=tkinter.TOP,
           anchor=tkinter.CENTER):
       tkinter.Frame.__init__(self, parent)
       tkinter.Label(self, text=title).grid(row=0, column=0)
       self.vars = []
       for idx, pick in enumerate(picks):
           row = int(idx / numCols)
           col = idx - row * numCols + 1
           var = tkinter.IntVar()
           chk = tkinter.Checkbutton(self, text=pick, variable=var,
                   command=self.state)
           if available:
               chk.select()
           else:
               chk.deselect()
               chk.config(state=tkinter.DISABLED)
           chk.grid(row=row, column=col, sticky=tkinter.W)
           self.vars.append(var)

   def state(self):
       return map((lambda var: var.get()), self.vars)


class ChoiceDialog(simpledialog.Dialog):
    def __init__(self, parent, title, text, items):
        self.selection = None
        self.__items = items
        self.__text = text
        super().__init__(parent, title=title)

    def body(self, parent):
        self.__message = tkinter.Message(parent, text=self.__text, aspect=400)
        self.__message.pack(expand=1, fill=tkinter.BOTH)
        self.__list = tkinter.Listbox(parent)
        self.__list.pack(expand=1, fill=tkinter.BOTH, side=tkinter.TOP)
        for item in self.__items:
            self.__list.insert(tkinter.END, item)
        return self.__list

    def validate(self):
        if not self.__list.curselection():
            return 0
        return 1

    def apply(self):
        self.selection = self.__items[self.__list.curselection()[0]]


