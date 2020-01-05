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
import xml.etree.ElementTree as ET
import shutil

def completeMappings(gnucashFilePath):
    # for each account, add an import-map with <slot:key>=<act:name>
    tree = ET.parse(gnucashFilePath)
    root = tree.getroot()
    newsitems = []
    for account in root.findall('./{http://www.gnucash.org/XML/gnc}book/{http://www.gnucash.org/XML/gnc}account'):
        print(account)
        name = None
        guid = None
        slotKeys = []
        slots = None
        for c in account:
            if c.tag == '{http://www.gnucash.org/XML/act}name':
                name = c.text
            elif c.tag == '{http://www.gnucash.org/XML/act}id':
                guid = c.text
            elif c.tag == '{http://www.gnucash.org/XML/act}slots':
                print('found slots')
                slots = c
                print(dir(slots))
                for slotAttributes in c.findall('slot/{http://www.gnucash.org/XML/slot}key'):
                    slotKeys.append(slotAttributes.text)
        print(name)
        print(guid)
        print(slotKeys)
        if not slots:
            slots = account.makeelement('{http://www.gnucash.org/XML/act}slots', {})
            account.append(slots)

        if not 'import-map' in slotKeys:
            print('adding slot')
            importMapSlot = slots.makeelement('slot', {})
            slots.append(importMapSlot)
            importMapKey = importMapSlot.makeelement('{http://www.gnucash.org/XML/slot}key', {})
            importMapKey.text = 'import-map'
            importMapSlot.append(importMapKey)
            importMapValue = importMapSlot.makeelement('{http://www.gnucash.org/XML/slot}value',
                    {'type': 'frame'})
            importMapSlot.append(importMapValue)

            accountMapSlot = importMapValue.makeelement('slot', {})
            importMapValue.append(accountMapSlot)
            accountMapKey = accountMapSlot.makeelement('{http://www.gnucash.org/XML/slot}key', {})
            accountMapKey.text = 'csv-account-map'
            accountMapSlot.append(accountMapKey)
            accountMapValue = accountMapSlot.makeelement('{http://www.gnucash.org/XML/slot}value',
                    {'type': 'frame'})
            accountMapSlot.append(accountMapValue)

            accountSlot = accountMapValue.makeelement('slot', {})
            accountMapValue.append(accountSlot)
            accountKey = accountSlot.makeelement('{http://www.gnucash.org/XML/slot}key', {})
            accountKey.text = name
            accountSlot.append(accountKey)
            accountValue = accountSlot.makeelement('{http://www.gnucash.org/XML/slot}value',
                    {'type': 'guid'})
            accountValue.text = guid
            accountSlot.append(accountValue)
            print(slots.findall('*'))
            print(slots.findall('*/*'))
            print(slots.findall('*/*/*'))

        tree.write(gnucashFilePath+'_tmp', encoding="utf-8", xml_declaration=True,
                short_empty_elements=False)

        with open(gnucashFilePath+'_tmp', "a") as fout:
            fout.write("\n<!-- Local variables: -->")
            fout.write("\n<!-- mode: xml        -->")
            fout.write("\n<!-- End:             -->")

        with open(gnucashFilePath+'_tmp', "r") as fin:
            with open(gnucashFilePath, 'w') as fout:
                for line in fin:
                    t = line.replace('ns0', 'gnc')
                    t = t.replace('ns1', 'cd')
                    t = t.replace('ns2', 'book')
                    t = t.replace('ns3', 'slot')
                    t = t.replace('ns4', 'cmdty')
                    t = t.replace('ns5', 'act')
                    fout.write(t)

        shutil.os.remove(gnucashFilePath+'_tmp')

if __name__ == '__main__':
    print("""
    ## WARNING ##
    \n
    These helpers might destroy your .gnucash file! Only proceed if you really know
    what you are doing!
    \n
    Only works on uncompressed files, be advised to review any changes with an
    appropriate diff tool and to keep a regular backup.
    """)
    if input('Proceed (y/n)?:') == 'y':
        gnucashFilePath = 'data/gnucash/Tagtrail_Accounting.gnucash'
        completeMappings(gnucashFilePath)
