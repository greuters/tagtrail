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
import re
import os
import shutil
import datetime
import time
import tkinter
import traceback
import database
import helpers
import gui_components

class EnrichedDatabase(database.Database):

    def __init__(self,
            accountingDataPath,
            accountingDate):

        super().__init__(f'{accountingDataPath}0_input/')
        toDate = accountingDate-datetime.timedelta(days=1)
        self.accountingDataPath = accountingDataPath
        self.inputTransactionsPath = self.accountingDataPath + \
                '0_input/export_Transactions_' + \
                helpers.DateUtility.strftime(self.previousAccountingDate,
                        database.PostfinanceTransactionList.filenameDateFormat) + '_' + \
                helpers.DateUtility.strftime(toDate,
                        database.PostfinanceTransactionList.filenameDateFormat) + '.csv'
        self.unprocessedTransactionsPath = self.accountingDataPath + \
                '5_output/unprocessed_Transactions_' + \
                helpers.DateUtility.strftime(self.previousAccountingDate) + '_' + \
                helpers.DateUtility.strftime(toDate) + '.csv'
        self.paymentTransactionsPath = f'{self.accountingDataPath}4_gnucash/paymentTransactions.csv'
        if not os.path.isfile(self.inputTransactionsPath):
            raise ValueError(
                    f'Missing required file {self.inputTransactionsPath}\n')

        if not os.path.isfile(self.unprocessedTransactionsPath):
            helpers.recreateDir(f'{self.accountingDataPath}4_gnucash/', self.log)
            helpers.recreateDir(f'{self.accountingDataPath}5_output/', self.log)
            self.log.info("copy {} to {}".format(self.inputTransactionsPath, self.unprocessedTransactionsPath))
            shutil.copy(self.inputTransactionsPath, self.unprocessedTransactionsPath)

        self.postfinanceTransactions = self.loadPostfinanceTransactions(
                self.previousAccountingDate, toDate)

    def loadPostfinanceTransactions(self, fromDate, toDate):
        loadedTransactions = database.Database.readCsv(
                self.unprocessedTransactionsPath,
                database.PostfinanceTransactionList)
        if loadedTransactions.dateFrom != fromDate:
            raise ValueError(
                    f"'Date from'='{loadedTransactions.dateFrom}' must " + \
                    f"be the previous accounting date '{fromDate}'")
        if loadedTransactions.dateTo != toDate:
            raise ValueError(
                    f"'Date to'='{loadedTransactions.dateTo}' must " + \
                    f"be one day before the current accounting date '{toDate}'")
        for transaction in loadedTransactions:
            transaction.memberId = transaction.inferMemberId(list(sorted(self.members.keys())))
            self.log.debug(f'inferred memberId {transaction.memberId}')
        return loadedTransactions

    @property
    def previousAccountingDate(self):
        return self.members.accountingDate


class Gui:
    def __init__(self,
            accountingDataPath,
            accountingDate):

        self.log = helpers.Log()
        self.accountingDataPath = accountingDataPath
        self.accountingDate = accountingDate

        self.inputCanvas = None
        self.buttonCanvas = None

        self.root = tkinter.Tk()
        self.root.report_callback_exception = self.reportCallbackException
        self.buttonCanvasWidth=200
        self.root.bind("<Tab>", self.switchInputFocus)
        self.root.bind("<Return>", self.switchInputFocus)
        self.root.bind("<Up>", self.switchInputFocus)
        self.root.bind("<Down>", self.switchInputFocus)
        self.root.bind("<Left>", self.switchInputFocus)
        self.root.bind("<Right>", self.switchInputFocus)
        self.root.bind("<Configure>", self.onResize)

        if self.loadData():
            self.root.geometry(str(self.root.winfo_screenwidth())+'x'+str(self.root.winfo_screenheight()))
            self.root.mainloop()

    def onResize(self, event):
        if event.widget == self.root:
            self.width=event.width
            self.height=event.height
            self.loadInputCanvas()
            self.loadButtonCanvas()

    def loadInputCanvas(self):
        # input canvas - one entry per transaction
        canvasWidth = self.width - self.buttonCanvasWidth
        if self.inputCanvas is not None:
            self.inputCanvas.destroy()
        self.inputCanvas = tkinter.Canvas(self.root,
               width=canvasWidth,
               height=self.height)
        self.inputCanvas.place(x=0, y=0)

        entryWidth = self.buttonCanvasWidth
        possibleMemberIds = list(sorted(self.db.members.keys()))
        y = 0
        self.entries = []
        for transaction in self.db.postfinanceTransactions:
            if transaction.creditAmount is None:
                continue

            label = tkinter.Message(self.inputCanvas,
                    text=transaction.notificationText,
                    anchor=tkinter.E,
                    width=canvasWidth-entryWidth)
            label.place(x=0, y=y)

            # need to update the screen to get the correct label height
            # caveat: during the update, a <Configure> event might be triggered
            # and invalidate the whole process => abort if we are outdated
            label.update()
            if not label.winfo_exists():
                return

            h = label.winfo_height()

            if transaction.memberId is None:
                mostLikely = transaction.mostLikelyMemberId(possibleMemberIds)
                text = '' if mostLikely is None else mostLikely
                confidence = 0
            else:
                text = transaction.memberId
                confidence = 1
            entry = gui_components.AutocompleteEntry(text, confidence, possibleMemberIds,
                    self.switchFocus, self.inputCanvas)
            entry.transaction = transaction
            entry.place(x=canvasWidth-entryWidth, y=y, w=entryWidth, h=h)
            self.entries.append(entry)
            y += h

    def switchFocus(self, event):
        # cudos to https://www.daniweb.com/programming/software-development/code/216830/tkinter-keypress-event-python
        if str(event.type) == "KeyPress" and event.char != event.keysym:
            # punctuation or special key, distinguish by event.keysym
            if event.keysym == "Return":
                event.widget.confidence=1
                event.widget.transaction.memberId = event.widget.text

            if event.keysym in ["Return", "Tab"]:
                nextUnclearEntry = self.nextUnclearEntry(event.widget)
                if not nextUnclearEntry is None:
                    nextUnclearEntry.focus_set()

            elif event.keysym == "Up":
                currentIndex = self.entries.index(event.widget)
                nextIndex = len(self.entries)-1 if currentIndex == 0 else currentIndex-1
                self.entries[nextIndex].focus_set()
            elif event.keysym == "Down":
                currentIndex = self.entries.index(event.widget)
                nextIndex = 0 if currentIndex == len(self.entries)-1 else currentIndex+1
                self.entries[nextIndex].focus_set()

        return event

    def nextUnclearEntry(self, selectedEntry):
        indicesOfUnclearEntries = [idx for idx, e in enumerate(self.entries) if e.confidence<1]
        if not indicesOfUnclearEntries:
            return None
        else:
            currentIndex = self.entries.index(selectedEntry)
            if max(indicesOfUnclearEntries) <= currentIndex:
                return self.entries[min(indicesOfUnclearEntries)]
            else:
                return self.entries[min(filter(lambda x: currentIndex < x,
                    indicesOfUnclearEntries))]


    def loadButtonCanvas(self):
        if self.buttonCanvas is not None:
            self.buttonCanvas.destroy()
        self.buttonCanvas = tkinter.Frame(self.root,
               width=self.buttonCanvasWidth,
               height=self.height)
        self.buttonCanvas.place(x=self.width - self.buttonCanvasWidth, y=0)
        self.buttons = {}
        self.buttons['saveAndExit'] = tkinter.Button(self.buttonCanvas,
                text='Save and exit', command=self.saveAndExit)
        self.buttons['saveAndExit'].bind('<Return>', self.saveAndExit)
        self.buttons['saveAndReloadDB'] = tkinter.Button(self.buttonCanvas,
                text='Save and reload current', command=self.saveAndReloadDB)
        self.buttons['saveAndReloadDB'].bind('<Return>', self.saveAndReloadDB)
        y = 60
        for b in self.buttons.values():
            b.place(relx=.5, y=y, anchor="center",
                    width=.8*self.buttonCanvasWidth)

            # need to update the screen to get the correct button height
            # caveat: during the update, a <Configure> event might be triggered
            # and invalidate the whole process => abort if we are outdated
            b.update()
            if not b.winfo_exists():
                return
            y += b.winfo_height()

    def reportCallbackException(self, exception, value, tb):
        traceback.print_exception(exception, value, tb)
        tkinter.messagebox.showerror('Abort Accounting', value)

    def saveAndExit(self, event=None):
        self.save()
        self.root.destroy()

    def loadData(self):
        """
        Load data and return True if any work remains to be done, else False
        """
        self.db = EnrichedDatabase(self.accountingDataPath,
                self.accountingDate)
        paymentTransactions = [t for t in self.db.postfinanceTransactions if
                t.creditAmount is not None]
        if len(paymentTransactions) == 0:
            tkinter.messagebox.showinfo(
                'Nothing to do', 'All payment transactions have been processed')
            return False
        return True

    def saveAndReloadDB(self, event=None):
        self.save()
        self.loadData()
        self.loadInputCanvas()
        return "break"

    def save(self):
        if os.path.isfile(self.db.paymentTransactionsPath):
            paymentTransactions = database.Database.readCsv(self.db.paymentTransactionsPath,
                    database.GnucashTransactionList)
        else:
            paymentTransactions = database.GnucashTransactionList()

        numberOfTransactions = len(paymentTransactions) + len(self.db.postfinanceTransactions)
        indicesToRemove = []
        for idx, pfTransaction in enumerate(self.db.postfinanceTransactions):
            self.log.debug(f'paymentTransactions = {[t.sourceAccount for t in paymentTransactions]}')
            self.log.debug(f'postfinanceTransactions = {[t.memberId for t in self.db.postfinanceTransactions]}')
            self.log.debug(f'indicesToRemove = {indicesToRemove}')
            if pfTransaction.memberId is None or \
                    not pfTransaction.memberId in self.db.members:
                continue
            self.log.debug(f'identified transaction for {pfTransaction.memberId}')
            gnucashTransaction = database.GnucashTransaction(
                pfTransaction.notificationText,
                pfTransaction.creditAmount,
                pfTransaction.memberId,
                self.db.config.get('tagtrail_bankimport', 'checking_account'),
                pfTransaction.bookingDate)
            if not gnucashTransaction in paymentTransactions:
                paymentTransactions.append(gnucashTransaction)
                indicesToRemove.append(idx)
                self.log.debug(f'marked transaction to be removed from postfinanceTransactions')
                assert(gnucashTransaction in paymentTransactions)
                assert(not gnucashTransaction in self.db.postfinanceTransactions)
            else:
                raise ValueError(f'Transaction {pfTransaction} exists in ' + \
                f'{self.db.paymentTransactionsPath} as well as ' + \
                f'{self.db.unprocessedTransactionsPath}. Remove ' + \
                f'{self.db.unprocessedTransactionsPath}, correct ' + \
                f'{self.db.inputTransactionsPath} and start ' + \
                'tagtrail_bankimport again.')
        self.db.postfinanceTransactions[:] = [transaction for idx, transaction in
                enumerate(self.db.postfinanceTransactions)
                if not idx in indicesToRemove]

        if numberOfTransactions != len(paymentTransactions) + \
                len(self.db.postfinanceTransactions):
                    raise AssertionError('numberOfTransactions is not ' + \
                            'consistent, please file a bug at ' + \
                            'https://github.com/greuters/tagtrail')

        database.Database.writeCsv(self.db.paymentTransactionsPath, paymentTransactions)
        database.Database.writeCsv(self.db.unprocessedTransactionsPath, self.db.postfinanceTransactions)

    def switchInputFocus(self, event):
        focused = self.root.focus_displayof()
        if not focused:
            return event
        elif isinstance(focused, gui_components.AutocompleteEntry):
            if focused.confidence == 1 and event.keysym in ('Tab', 'Return'):
                self.buttons['saveAndExit'].focus_set()
        elif event.keysym == 'Tab':
            focused.tk_focusNext().focus_set()
        else:
            return event
        return 'break'

if __name__== "__main__":
    parser = argparse.ArgumentParser(
        description='Load transactions exported from Postfinance, ' + \
                'recognize payments from members and store unprocessed ' + \
                'transactions for manual entry to GnuCash.')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    parser.add_argument('--accountingDate',
            dest='accountingDate',
            type=helpers.DateUtility.strptime,
            default=helpers.DateUtility.todayStr(),
            help="Date of the new accounting, fmt='YYYY-mm-dd'",
            )
    args = parser.parse_args()
    Gui(args.accountingDir, args.accountingDate)
