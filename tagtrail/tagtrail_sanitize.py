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

lista = ['a', 'actions', 'additional', 'also', 'an', 'and', 'angle', 'are', 'as', 'be', 'bind', 'bracket', 'brackets', 'button', 'can', 'cases', 'configure', 'course', 'detail', 'enter', 'event', 'events', 'example', 'field', 'fields', 'for', 'give', 'important', 'in', 'information', 'is', 'it', 'just', 'key', 'keyboard', 'kind', 'leave', 'left', 'like', 'manager', 'many', 'match', 'modifier', 'most', 'of', 'or', 'others', 'out', 'part', 'simplify', 'space', 'specifier', 'specifies', 'string;', 'that', 'the', 'there', 'to', 'type', 'unless', 'use', 'used', 'user', 'various', 'ways', 'we', 'window', 'wish', 'you']


class AutocompleteEntry(ttk.Combobox):
    def __init__(self, lista, entryBefore, *args, **kwargs):
        Entry.__init__(self, *args, **kwargs)
        self.lista = lista
        self.entryBefore = entryBefore
        print(self.entryBefore)
        self.var = self["textvariable"]
        if self.var == '':
            self.var = self["textvariable"] = StringVar()

        self.var.trace('w', self.changed)
        self.bind("<Return>", self.selection)
        self.bind("<Up>", self.up)
        self.bind("<Down>", self.down)
        self.bind("<Tab>", self.next)

        self.prev_val = ""
        self.lb_up = False

    def next(self, event):
        print("select next entry with low confidence")


    def changed(self, name, index, mode):  
        print(self.var.get())

        if self.var.get() == '':
            if self.lb_up:
                self.lb.destroy()
                self.lb_up = False
        else:
            words = self.comparison()
            print(words)
            if len(words) == 1 and len(self.prev_val) < len(self.var.get()):
                if self.lb_up:
                    self.lb.destroy()
                    self.lb_up = False
                self.delete(0, END)
                self.insert(0, words[0])

            elif words:
                if not self.lb_up:
                    self.lb = Listbox()
                    self.lb.place(x=self.winfo_x(), y=self.winfo_y()+self.winfo_height())
                    self.lb_up = True
                
                self.lb.delete(0, END)
                for w in words:
                    self.lb.insert(END,w)
            else:
                if self.lb_up:
                    self.lb.destroy()
                    self.lb_up = False
                self.var.set(self.prev_val)

        self.prev_val = self.var.get()
        
    def selection(self, event):
        print("selection")

        if self.lb_up:
            self.var.set(self.lb.get(ACTIVE))
            self.lb.destroy()
            self.lb_up = False
            self.icursor(END)

    def up(self, event):

        if self.lb_up:
            if self.lb.curselection() == ():
                index = '0'
            else:
                index = self.lb.curselection()[0]
            if index != '0':                
                self.lb.selection_clear(first=index)
                index = str(int(index)-1)                
                self.lb.selection_set(first=index)
                self.lb.activate(index) 

        elif self.entryBefore:
            self.entryBefore.focus_set()


    def down(self, event):

        if self.lb_up:
            if self.lb.curselection() == ():
                index = '0'
            else:
                index = self.lb.curselection()[0]
            if index != END:                        
                self.lb.selection_clear(first=index)
                index = str(int(index)+1)        
                self.lb.selection_set(first=index)
                self.lb.activate(index) 

    def comparison(self):
        if not self.lista:
            return [self.var.get()]
        pattern = re.compile(self.var.get().upper() + '.*')
        return [w for w in self.lista if re.match(pattern, w.upper())]

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


    dataFilePath = 'data/database/{}'
    db = Database(dataFilePath.format('mitglieder.csv'),
            dataFilePath.format('produkte.csv'))
    sheet = ProductSheet("not", "known", "yet",
            ProductSheet.maxQuantity(), db)
    entryBefore = None
    for box in sheet._boxes:
        if box.name == "nameBox":
            choices = db._products.keys()
        elif box.name == "unitBox":
            choices = []
        elif box.name == "priceBox":
            choices = []
        elif box.name.find("dataBox") != -1:
            choices = db._members.keys()
        else:
            continue

        (x1, y1) = box.pt1
        x1, y1 = x1*ratio, y1*ratio
        (x2, y2) = box.pt2
        x2, y2 = x2*ratio, y2*ratio
        entryBefore = AutocompleteEntry(choices, entryBefore, root)
        entryBefore.place(x=canvas_w+x1, y=y1, w=x2-x1, h=y2-y1)

    root.mainloop()
