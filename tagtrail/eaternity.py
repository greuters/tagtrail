from .database import Database
from . import helpers

import argparse
import requests
import json

class EaternityApi:
    querystring = {'transient': 'true'}
    headers = {
        }

    def __init__(self, config, apiKey = None):
        """
        :param config: loaded config/tagtrail.cfg
        :type config: :class: `configparser.ConfigParser`
        :param apiKey: optional apiKey for eaternity. if None is given, apiKey
            will be loaded from credentials.cfg
        :type apiKey: str
        """
        self.logger = logging.getLogger('tagtrail.eaternity.EaternityApi')
        self.config = config
        self.kitchenId = self.config.get('eaternity', 'kitchenId')
        self.kitchenLocation = self.config.get('eaternity', 'kitchenLocation')
        self.baseUrl = self.config.get('eaternity', 'baseUrl')
        if apiKey is None:
            keyring = helpers.Keyring(self.config.get('general',
                'password_file_path'))
            apiKey = keyring.get_and_ensure_password('eaternity', 'apiKey')

        self.headers = {
                'Content-Type': "Application/Json",
                'Authorization': apiKey,
                'Host': "co2.eaternity.ch",
                'Accept-Encoding': "gzip, deflate",
                'Cookie': "__cfduid=d53ccfea6402c4eb1fbc89a4c387dcb311571412595",
                'Connection': "keep-alive",
                }
        if not self.kitchenId in self.getKitchens():
            self.createKitchen()

    def getKitchens(self):
        response = requests.request("GET",
                f'{self.baseUrl}kitchens',
                headers=self.headers).json()
        if not 'kitchens' in response:
            raise ValueError('failed to retrieve kitchens', response)
        return response['kitchens']

    def createKitchen(self):
        kitchen={'name': self.kitchenId,
                'location': self.kitchenLocation
                }
        payload = {'kitchen': kitchen}
        response = requests.request("PUT",
                f'{self.baseUrl}kitchens/{self.kitchenId}',
                data=json.dumps(payload),
                headers=self.headers).json()
        if not 'kitchen' in response or \
                not 'id' in response['kitchen'] or \
                not self.kitchenId == response['kitchen']['id']:
            raise ValueError('failed to create kitchen', response)

    def co2Value(self, product):
        ingredients=[{'id': 0,
                'names': [{'language': 'DE', 'value': product.eaternityName}],
                'amount': product.amount,
                'unit': product.unit,
                'origin': product.origin,
                'transport': product.transport,
                'production': product.production[0] if 0<len(product.production) else '',
                'conservation': product.conservation[0] if 0<len(product.conservation) else ''
                }]
        recipe={'kitchen-id': self.kitchenId,
                'titles': [{'language': 'DE', 'value': 'speichersortiment'}],
                'date': helpers.DateUtility.todayStr(),
                'servings': 1,
                'location': self.kitchenLocation,
                'ingredients': ingredients
                }
        payload={'recipe': recipe}
        self.logger.debug(f'payload: {payload}')
        response = requests.request("POST",
                f'{self.baseUrl}recipes',
                data=json.dumps(payload),
                headers=self.headers,
                params=self.querystring).json()
        self.logger.debug(f'response: {response}')
        if 'status' in response and response['status'] == 'BAD_REQUEST':
            raise ValueError(response)
        elif 'statuscode' in response:
            if response['statuscode'] == 602:
                raise ValueError('no automatic match found '
                        + f"for ingredient '{product.eaternityName}'")
            elif response['statuscode'] != 200:
                raise ValueError(response.text)
            return response['recipe']['co2-value']
        else:
            raise ValueError(response)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test tagtrail_account')
    parser.add_argument('--apiKey',
            default=None,
            help='API key needed to update co2 values; if this argument is '
            'missing API key is read from credential store')
    args = parser.parse_args()

    db = Database(f'data/next/0_input/')
    api = EaternityApi(db.config, args.apiKey)
    for product in db.products.values():
        print(f'productName={product.id}, amount={product.amount}, unit={product.unit}, gCo2e={api.co2Value(product)}')
