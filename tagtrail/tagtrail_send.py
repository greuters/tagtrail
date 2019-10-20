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
from abc import ABC, abstractmethod
from string import Template
import helpers
import database
import time
import csv
import imaplib
import smtplib
import ssl
from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase

class MailSender(ABC):
    debuggingMode = True

    def __init__(self,
            liquidityThreshold,
            invoiceIBAN,
            accessCode,
            accountingPath,
            db):
        self.liquidityThreshold = liquidityThreshold
        self.invoiceIBAN = invoiceIBAN
        self.accessCode = accessCode
        self.log = helpers.Log(helpers.Log.LEVEL_DEBUG)
        self.billPath = accountingPath + '3_bills/'
        self.templatePath = accountingPath + '0_input/templates/'
        self.db = db
        self.bills = [database.Database.readCsv(
            f'{self.billPath}{member.id}.csv', database.Bill)
            for member in db.members.values()]

        self.emailTemplate = self.readTemplate(self.templatePath+'email.txt')
        self.invoiceAboveThresholdTemplate = self.readTemplate(
                self.templatePath+'invoice_above_threshold.txt')
        self.invoiceBelowThresholdTemplate = self.readTemplate(
                self.templatePath+'invoice_below_threshold.txt')

        self.accountantName = input('Accountant name: ')
        self.mail_user = 'info@speichaer.ch'
        self.mail_pass = input('Password for {}: '.format(self.mail_user))
        self.mail_host = 'mail.cyon.ch'

    def readTemplate(self, filename):
        with open(filename, 'r', encoding='utf-8') as template_file:
            template_file_content = template_file.read()
        return Template(template_file_content)

    def sendBills(self):
        if self.debuggingMode:
            testEmail = input('Test account to send emails to: ')

        for bill in self.bills:
            invoiceTextTemplate = self.invoiceAboveThresholdTemplate \
                    if self.liquidityThreshold < bill.currentBalance() else \
                    self.invoiceBelowThresholdTemplate

            for email in self.db.members[bill.memberId].emails:
                if self.debuggingMode:
                    self.log.info(f'would send email to {email}, replaced by {testEmail}: ')
                    email = testEmail

                name = self.db.members[bill.memberId].name
                self.log.info('Sending email to {}, {}'.format(email, name))
                body = self.emailTemplate.substitute(
                            INVOICE_TEXT=invoiceTextTemplate.substitute(
                                LIQUIDITY_THRESHOLD=helpers.formatPrice(self.liquidityThreshold, 'CHF'),
                                ACCESS_CODE=self.accessCode,
                                MEMBER_ID=bill.memberId,
                                INVOICE_IBAN=self.invoiceIBAN),
                            MEMBER_NAME=name,
                            BILL=str(bill),
                            TOTAL_PAYMENTS=helpers.formatPrice(bill.totalPayments, 'CHF'),
                            PREVIOUS_ACCOUNTING_DATE=bill.previousAccountingDate,
                            PREVIOUS_BALANCE=helpers.formatPrice(bill.previousBalance, 'CHF'),
                            CURRENT_ACCOUNTING_DATE=bill.currentAccountingDate,
                            CURRENT_BALANCE=helpers.formatPrice(bill.currentBalance(), 'CHF'),
                            LIQUIDITY_THRESHOLD=helpers.formatPrice(self.liquidityThreshold, 'CHF'),
                            INVOICE_IBAN=self.invoiceIBAN,
                            MEMBER_ID=bill.memberId,
                            ACCESS_CODE=self.accessCode,
                            REPLY_TO_ADDRESS=self.mail_user,
                            ACCOUNTANT_NAME=self.accountantName
                            )

                filename = bill.memberId+'.csv'
                self.sendEmail(email,
                        'Abrechnung vom {}'.format(bill.currentAccountingDate),
                        body, f'{self.billPath}{filename}', filename)

    def sendEmail(self, to, subject, body, path, attachmentName):
        message = MIMEMultipart()
        message["From"] = self.mail_user
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        with open(path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)

        part.add_header(
            "Content-Disposition",
            "attachment; filename= \"" + attachmentName + "\"",
        )
        message.attach(part)
        text = message.as_string()

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.mail_host, 465, context=context) as server:
            result = server.login(self.mail_user, self.mail_pass)
            server.sendmail(self.mail_user, to, text)

        imap = imaplib.IMAP4_SSL(self.mail_host, 993)
        imap.login(self.mail_user, self.mail_pass)
        imap.append('INBOX.Sent', '\\Seen', imaplib.Time2Internaldate(time.time()), text.encode('utf8'))
        imap.logout()



if __name__ == '__main__':
    accountingDate = '2019-11-03'
    accountingPath = 'data/next/'
    #accountingPath = f'data/accounting_{accountingDate}/'

    db = database.Database(f'{accountingPath}0_input/')
    sender = MailSender(100, 'CH 123 123 123', '1234#', accountingPath, db)
    sender.sendBills()
