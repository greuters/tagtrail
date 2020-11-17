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
from tkinter import messagebox
from abc import ABC, abstractmethod
import traceback
import tkinter
import time
import re
import sys

from . import helpers

#TODO: adapt to use normal ttk.ComboBox functionality
class AutocompleteEntry(tkinter.Entry):
    """
    All input is uppercased before processing.
    """
    def __init__(self, text, confidence, possibleValues, releaseFocus, enabled,
            listBoxParent, listBoxX, listBoxY, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.possibleValues = [v.upper() for v in possibleValues]
        self.__releaseFocus = releaseFocus
        self.__log = helpers.Log()
        self.__previousValue = ""
        self.__listBox = None
        self.__var = self["textvariable"]
        if self.__var == '':
            self.__var = self["textvariable"] = tkinter.StringVar()
        self.text = text
        self.enabled = enabled
        self.confidence = confidence
        self.listBoxParent = listBoxParent
        self.listBoxX = listBoxX
        self.listBoxY = listBoxY

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
        self.__var.set(self.__var.get().upper())
        self.__log.debug('changed var = {}', self.text)
        self.confidence = 0

        if self.text == '':
            self.destroyListBox()
        else:
            if self.text.strip() == '':
                words = self.possibleValues
            else:
                words = self.comparison(self.text)
            self.__log.debug('possible words = {}', words)
            if not words:
                self.text = self.__previousValue
                self.__var.set(self.__previousValue)
            else:
                longestCommonPrefix = self.longestCommonPrefix(words)
                self.__log.debug('longestCommonPrefix(words) = {}', self.longestCommonPrefix(words))
                if longestCommonPrefix != self.text:
                    self.delete(0, tkinter.END)
                    self.insert(0, longestCommonPrefix)

                if len(words) == 1:
                        self.destroyListBox()

                else:
                    if not self.__listBox:
                        self.__listBox = tkinter.Listbox(self.listBoxParent)
                        self.__listBox.place(x=self.listBoxX, y=self.listBoxY)

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
                    self.setArbitraryText(p)
                    break
        return "break"

    def focus_set(self):
        super().focus_set()
        # initialize with prefix
        if self.text == '' and self.confidence == 0:
            self.delete(0, tkinter.END)
            self.insert(0, self.longestCommonPrefix(self.possibleValues))
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
        word = words[0]
        prefixes = [word[0:i] for i in range(len(word)+1)]
        for p in sorted(prefixes, reverse=True):
            isPrefix = [(w.find(p) == 0) for w in words]
            if len(p) == 0 or False not in isPrefix:
                return p

    def comparison(self, word):
        if not self.possibleValues:
            return [word]
        return [w for w in self.possibleValues if w.find(word) == 0]

    @property
    def enabled(self):
        return self.cget('state') == 'normal'

    @enabled.setter
    def enabled(self, enabled):
        """
        Enable/disable user input and autocorrection.
        """
        if enabled:
            self.__var.trace_id = self.__var.trace('w', self.varTextChanged)
            self.configure(state='normal')
        else:
            self.__var.trace_vdelete('w', self.__var.trace_id)
            self.configure(state='disabled')

    @property
    def text(self):
        return self.__var.get()

    @text.setter
    def text(self, text):
        """
        If text is not in self.possibleValues or '', nothing happens. To avoid this
        restriction, set self.enabled = False and call self.setArbitraryText
        """
        if text != '' and not text.upper() in self.possibleValues:
            return
        self.__var.set(text.upper())

    def setArbitraryText(self, text):
        """
        Sets text without constraining to self.possibleValues.
        Note that, if self.enabled == True, the value will be subjected to
        autocorrection.
        """
        self.__var.set(text.upper())

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

class BaseGUI(ABC):
    """
    Base class for graphical user interfaces interacting with a model.
    Handles standard tasks like window resizing.

    :param initWidth: initial width of the root window
    :type initWidth: int
    :param initHeight: initial width of the root window
    :type initHeight: int
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    """
    buttonFrameWidth=200
    progressBarLength = 400
    refreshTimeout = 50 # in ms

    def __init__(self,
            initWidth = None,
            initHeight = None,
            log = helpers.Log(helpers.Log.LEVEL_INFO)):
        self.log = log
        self.abortingProcess = False
        self.__lastConfigureTimestamp = time.time_ns()
        self.buttonFrame = None
        self.buttons = {}

        self.root = tkinter.Tk()
        self.root.report_callback_exception = self.reportCallbackException
        self.root.minsize(*self.get_minsize())

        if initWidth is None or initHeight is None:
            if sys.platform == "linux" or sys.platform == "linux2":
                self.root.attributes('-zoomed', True)
            elif sys.platform == "darwin":
                self.root.attributes('-zoomed', True)
            elif sys.platform == "win32":
                self.root.state('zoomed')
        else:
            self.root.geometry(f'{initWidth}x{initHeight}+0+0')

        self.root.update()
        self.width = self.root.winfo_width()
        self.height = self.root.winfo_height()

        self.populateRoot()
        self.root.bind("<Configure>", self.__configure)
        self.root.mainloop()

    def __configure(self, event):
        if not event.widget == self.root:
            return None
        now = time.time_ns()
        self.__lastConfigureTimestamp = now
        self.root.after(self.refreshTimeout, lambda: self.__deferredRefresh(event, now))

    def __deferredRefresh(self, event, timestamp):
        if timestamp != self.__lastConfigureTimestamp:
            return

        self.width = event.width
        self.height = event.height
        self.populateRoot()

    def get_minsize(self):
        """
        Query minimal window size of root.

        :return: (width, height)
        :rtype: (int, int)
        """
        return (800, 600)

    @abstractmethod
    def populateRoot(self):
        """
        (Re-)create widgets on self.root, taking care to destroy existing widgets
        from a previous call if necessary.
        """
        pass

    def setupProgressIndicator(self, progressMessage = 'Progress'):
        """
        Setup progress indication for the user before starting a long running
        process.

        Note: call self.updateProgressIndicator regularly to keep the user
        informed and stop processing if self.abortingProcess == True.

        When you are done processing, the indicator should be removed by a call
        to self.destroyProgressIndicator.

        :param progressMessage: one-line message to the user about what happens
        :type progressMessage: str
        """
        self.abortingProcess = False

        self.__progressWindow = tkinter.Toplevel()
        self.__progressWindow.title(progressMessage)
        self.__progressWindow.protocol("WM_DELETE_WINDOW", self.__abortProcess)
        self.__progressBar = tkinter.ttk.Progressbar(self.__progressWindow, length=self.progressBarLength, mode='determinate')
        self.__progressBar.pack(pady=10, padx=20)
        abortButton = tkinter.Button(self.__progressWindow, text='Abort',
            command=self.__abortProcess)
        abortButton.bind('<Return>', self.__abortProcess)
        abortButton.pack(pady=10)

    def updateProgressIndicator(self, percentage, progressMessage = None):
        """
        Update progress indication.

        :param percentage: progress made in a scale of 0..100
        :type percentage: float

        :param progressMessage: optional one-line message to the user about
            what happens. If None is given, the message is not updated.
            :type progressMessage: str
        """
        self.__progressBar['value'] = percentage
        if progressMessage is not None:
            self.__progressWindow.title(progressMessage)
        self.__progressWindow.update()

    def destroyProgressIndicator(self):
        """
        Stop indicating progress to the user.
        """
        if self.__progressWindow:
            self.__progressWindow.destroy()
            self.__progressWindow = None

    def __abortProcess(self):
        """
        Stop processing on user request.

        self.abortingProgress is set to True which should interrupt the running
        process if handled adequately, and the progress indication is reset.
        """
        self.abortingProcess = True
        self.destroyProgressIndicator()

    def reportCallbackException(self, exception, value, tb):
        traceback.print_exception(exception, value, tb)
        messagebox.showerror('Abort tagtrail', value)

    def addButtonFrame(self, buttons):
        """
        Add a frame with buttons to the east side of self.root

        :param buttons: list of triples (buttonId, text, command) to create
            buttons from and add them to self.buttons. self.buttons[buttonId]
            will have the given text and the command is a callback associated
            with clicking the button or hitting Return while it is focused
        :type buttons: list of triples (str, str, func), where func takes one
            positional argument (event)
        """
        if self.buttonFrame is None:
            self.buttonFrame = tkinter.Frame(self.root)
        self.buttonFrame.place(x=self.width - self.buttonFrameWidth,
                y=0,
               width=self.buttonFrameWidth,
               height=self.height)
        for w in self.buttonFrame.winfo_children():
            w.destroy()

        y = 60
        self.buttons = {}
        for buttonId, text, command in buttons:
            b = tkinter.Button(self.buttonFrame, text=text)
            b.bind('<Button-1>', command)
            b.bind('<Return>', command)
            b.place(relx=.5, y=y, anchor="center",
                    width=.8*self.buttonFrameWidth)

            # need to update the screen to get the correct button height
            # caveat: during the update, a <Configure> event might be triggered
            # and invalidate the whole process => abort if we are outdated
            b.update()
            if not b.winfo_exists():
                return
            y += b.winfo_height()
            self.buttons[buttonId] = b
