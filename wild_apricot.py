import base64
import datetime
import requests
import json
import pandas as pd
import time

from secrets import wild_apricot_api_key as api_key

auth_endpoint = "https://oauth.wildapricot.org/auth/token"
api_endpoint = "https://api.wildapricot.org/v2.1"

"""
Membership Questions
- How many members do we have of each type?
- How many members are in good/bad standing?
- What is quorum?
- Who is eligible to run for the board?
- How many people are authoirzed for each thing?
- How many people voted in the last vote?
"""


class WildApricotAPI:
    def __init__(self):
        self.authenticate()

        self.__contact_df = None

    def authenticate(self, scope=None):
        scope = "auto" if scope is None else scope
        data = {
            "grant_type": "client_credentials",
            "scope": scope
        }

        response = requests.post(
            auth_endpoint,
            data=data,
            headers={
                "ContentType": "application/x-www-form-urlencoded",
                "Authorization": ("Basic " +
                                  base64.standard_b64encode(
                                            ('APIKEY:' + api_key).encode())
                                        .decode())
            }
        )
        self.auth = response.json()
        self.expiration = (datetime.datetime.now() +
                           datetime.timedelta(seconds=self.auth['expires_in'] - 100))

    @property
    def token(self):
        if datetime.datetime.now() > self.expiration:
            self.authenticate()
        return self.auth['access_token']

    def get(self, endpoint, data=None):
        """
        Generic function for hitting an API endpoint and doing the proper error handling.

        :param endpoint: The endpoint to hit. Can either be a full or relative URL
        :type endpoint: str

        :param data: Any additional data that should be sent with request.
        :type data:
        """
        if endpoint.startswith("http"):
            url = endpoint
        elif endpoint.startswith("/"):
            url = "{}{}".format(api_endpoint, endpoint)
        else:
            url = "{}/{}".format(api_endpoint, endpoint)

        response = requests.get(
            url,
            data=data,
            headers= {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer " + self.token,
            }
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print("404: Probably invalid endpoint")
        else:
            print("ERROR IN REQUEST: {}".format(response.content))
        return response

    def account_id(self):
        """
        Get the PS1 account id.

        :rtype: str
        """
        return self.get('/accounts')[0]['Id']

    def authorization_types(self):
        """
        Get labels and ids for all types of authorizations present in the WildApricot system.

        :returns: The dictionary from authorization Label -> Id
        :rtype: dict
        """
        contact_fields = self.get("/accounts/{}/contactfields"
                                  .format(self.account_id()))
        auth_field_def = [s for s in contact_fields
                            if s['FieldName'] == 'Managed Authorizations'][0]
        auth_types = {i['Label']: i['Id'] for i in auth_field_def['AllowedValues']}
        return auth_types

    def authorizations(self):
        """
        Get the matrix of authorizations for all users. The columns will be the authorization label,
        the rows will be a the users (indexed by ContactId), and the values will be True or False.

        :rtype: pd.DataFrame
        """
        if self.__contact_df is None:
            self.contact_info()

        authorization_data = list()
        for cid, value in self.__contact_df['Authorizations'].items():
            row_data = {
                'ContactId': cid
            }

            if isinstance(value, list):
                for auth_type in value:
                    row_data[auth_type] = True
            authorization_data.append(row_data)
        return pd.DataFrame(authorization_data).fillna(False).set_index('ContactId')

    def contact_info(self, sensitive=True):
        """
        Get basic contact information for all users. By default it will hide sensitive information
        such as name and email.

        :param sensitive: Whether or not to hide sensitive information (defaults to True)
        :type sensitive: bool

        :rtype: pd.DataFrame
        """
        account_id = self.account_id()
        retry_count = 5

        req_url = self.get("/accounts/{}/contacts".format(account_id))['ResultUrl']
        resp = self.get(req_url)
        tries = 0
        while 'Contacts' not in resp and tries < retry_count:
            resp = self.get(req_url)
            tries += 1
            time.sleep(1)
        contacts = resp['Contacts']

        contact_data = list()
        for contact in contacts:
            row_data = {
                'ContactId': contact['Id'],
                'Email': "*****@****.***" if sensitive else contact['Email'],
                'FirstName': "*****" if sensitive else contact['FirstName'],
                'LastName': "*****" if sensitive else contact['LastName'],
                'Status': contact.get('Status'),
                'MembeshipEnabled': contact.get('MembershipEnabled'),
                'TermsOfUseAccepted': contact['TermsOfUseAccepted'],
            }

            if 'MembershipLevel' in contact:
                row_data['MembershipLevel'] = contact['MembershipLevel']['Name']

            # Map all field values into a dict for convenience
            field_values = {val['FieldName']: val['Value']
                            for val in contact['FieldValues']}

            # Get list of authorizations
            if 'Managed Authorizations' in field_values:
                authorizations = [i['Label']
                                  for i in field_values['Managed Authorizations']]
                row_data['Authorizations'] = authorizations

            contact_data.append(row_data)
        self.__contact_df = pd.DataFrame(contact_data).set_index('ContactId')
        return self.__contact_df

    #YYYY-MM-DD
    def payment_info(self, start_date=None, end_date=None):
        """
        Retrieve all payment information. Note that this function takes a long time to execute.
        The table that is returned will be sorted by payment date descending.

        :param start_date: The optional start date formatted as YYYY-MM-DD.
                           If not given, will use now.
        :type start_date: str

        :param end_date: The optional end date formatted as YYYY-MM-DD.
                         If not given, will go as far back as possible.
        :type end_date: str

        :rtype: pd.DataFrame
        """
        if self.__contact_df is None:
            self.contact_info()

        account_id = self.account_id()
        contact_ids = self.__contact_df.index

        payment_data = list()
        for i, cid in enumerate(contact_ids):
            if i%40 == 0:
                print("{} / {}".format(i, len(contact_ids)))

            # Construct request parameters
            params = "contactId={}".format(cid)
            if start_date is not None:
                params += "&StartDate={}".format(start_date)
            if end_date is not None:
                params += "&EndDate={}".format(end_date)

            payments = self.get('/Accounts/{}/Payments?{}'
                                .format(account_id, params))['Payments']

            for payment in payments:
                row_data = {
                    'ContactId': cid,
                    'PaymentDate': payment['CreatedDate'].split('T')[0],
                    'PaymentId': payment['Id'],
                    'AllocatedValue': payment['AllocatedValue'],
                    'Value': payment['Value'],
                    'Comment': payment['Comment'],
                    'Type': payment['Type'],
                }

                if payment['Tender'] is not None:
                    row_data.update({
                        'TenderId': payment['Tender']['Id'],
                        'TenderName': payment['Tender']['Name'],
                    })

                payment_data.append(row_data)
        return pd.DataFrame(payment_data).sort_values(by="PaymentDate", ascending=False)
