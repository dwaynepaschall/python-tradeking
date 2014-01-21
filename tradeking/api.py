# -*- coding: utf-8 -*-

import types
import urlparse

import requests_oauthlib as roauth
import pandas as pd

import utils


BASE_URL = 'https://api.tradeking.com/v1'
_DATE_KEYS = ('date', 'datetime', 'divexdate', 'divpaydt', 'timestamp',
              'pr_date', 'wk52hidate', 'wk52lodate', 'xdate')
_FLOAT_KEYS = ('ask', 'bid', 'chg', 'cl', 'div', 'dollar_value', 'eps',
               'hi', 'iad', 'idelta', 'igamma', 'imp_volatility', 'irho',
               'itheta', 'ivega', 'last', 'lo', 'opn', 'opt_val', 'pchg',
               'pcls', 'pe', 'phi', 'plo', 'popn', 'pr_adp_100', 'pr_adp_200',
               'pr_adp_50', 'prbook', 'prchg', 'strikeprice', 'volatility12',
               'vwap', 'wk52hi', 'wk52lo', 'yield')
_INT_KEYS = ('asksz', 'basis', 'bidsz', 'bidtick', 'days_to_expiration',
             'incr_vl', 'openinterest', 'pr_openinterest', 'prem_mult', 'pvol',
             'sho', 'tr_num', 'vl', 'xday', 'xmonth', 'xyear')


def option_symbol(underlying, expiration, call_put, strike):
    call_put = call_put.upper()
    if call_put not in ('C', 'P'):
        raise ValueError("call_put value not one of ('C', 'P'): %s" %
                         call_put)

    expiration = pd.to_datetime(expiration).strftime('%y%m%d')

    strike = str(int(strike * 1000))
    strike = ('0' * (8 - len(strike))) + strike

    return '%s%s%s%s' % (underlying, expiration, call_put, strike)


def parse_option_symbol(symbol):
    strike = float(symbol[-8:]) / 1000
    call_put = symbol[-9:-8].upper()
    expiration = pd.to_datetime(symbol[-15:-9])
    underlying = symbol[:-15].upper()
    return underlying, expiration, call_put, strike


def _quotes_to_df(quotes):
    if not isinstance(quotes, types.ListType):
        quotes = [quotes]
    df = pd.DataFrame.from_records(quotes, index='symbol')

    for col in df.keys().intersection(_DATE_KEYS):
        df[col] = pd.to_datetime(df[col])

    for col in df.keys().intersection(_INT_KEYS):
        df[col] = df[col].str.replace(r'[$,%]', '').astype('int')

    for col in df.keys().intersection(_FLOAT_KEYS):
        df[col] = df[col].str.replace(r'[$,%]', '').astype('float')

    if 'put_call' in df:
        df.set_index(['undersymbol', 'xdate', 'put_call', 'strikeprice'],
                     drop=False, inplace=True)

    return df


# TODO(jkoelker) Would be nice to do a proper DSL
class OptionQuery(object):
    FIELDS = ('strikeprice', 'xdate', 'xmonth', 'xyear', 'put_call', 'unique')
    OPS = {'<': 'lt', 'lt': 'lt',
           '>': 'gt', 'gt': 'gt',
           '>=': 'gte', 'gte': 'gte',
           '<=': 'lte', 'lte': 'lte',
           '=': 'eq', '==': 'eq', 'eq': 'eq'}

    def __init__(self, query):
        if isinstance(query, types.StringTypes):
            query = [query]

        self._query = []

        for part in query:
            field, op, value = part.split()
            field = field.lower()

            if field not in self.FIELDS or op not in self.OPS:
                continue

            self._query.append((field, self.OPS[op], value))

    def __str__(self):
        return ' AND '.join(['%s-%s:%s' % (field, op, value)
                             for field, op, value in self._query])


class API(object):
    def __init__(self, consumer_key, consumer_secret,
                 oauth_token, oauth_secret):
        self._api = roauth.OAuth1Session(client_key=consumer_key,
                                         client_secret=consumer_secret,
                                         resource_owner_key=oauth_token,
                                         resource_owner_secret=oauth_secret)

    def join(self, *paths, **kwargs):
        if len(paths) == 1:
            paths = paths[0]

        if kwargs.get('clean', True):
            paths = [p.rstrip('/') for p in paths]

        return '/'.join(paths)

    def request(self, method, url, format='json', decode=True, **kwargs):
        if format:
            url = '.'.join((url, format))

        r = self._api.request(method, url, **kwargs)

        if decode:
            r = r.json()

        return r

    def get(self, url, format='json', decode=True, **kwargs):
        return self.request('GET', url=url, format=format, decode=decode,
                            **kwargs)

    def post(self, url, format='json', decode=True, **kwargs):
        return self.request('POST', url=url, format=format, decode=decode,
                            **kwargs)


class Account(object):
    def __init__(self, api, account_id):
        self._api = api
        self.account_id = account_id

    def _get(self, what=None, **kwargs):
        params = [BASE_URL, 'accounts', self.account_id]

        if what is not None:
            params.append(what)

        path = self._api.join(params)
        return self._api.get(path, **kwargs)

    def _balances(self, **kwargs):
        return self._get('balances', **kwargs)

    def _history(self, date_range='all', transactions='all', **kwargs):
        params = {'range': date_range, 'transactions': transactions}
        return self._get('history', params=params, **kwargs)

    def _holdings(self, **kwargs):
        return self._get('holdings', **kwargs)

    def _orders(self, **kwargs):
        return self._get('orders', **kwargs)

    @property
    def balances(self):
        r = self._balances()
        return r['response']['accountbalance']

    def history(self, date_range='all', transactions='all'):
        r = self._history(date_range=date_range, transactions=transactions)
        return r['response']['transactions']['transaction']

    @property
    def holdings(self):
        r = self._holdings()
        return r['response']['accountholdings']['holding']

    # TODO(jkoelker)
    def order(self, order, preview=True):
        pass

    @property
    def orders(self):
        r = self._orders()
        return r['response']['orderstatus']


class News(object):
    def __init__(self, api):
        self._api = api

    def _article(self, article_id, **kwargs):
        path = self._api.join(BASE_URL, 'market', 'news', article_id)
        return self._api.get(path, **kwargs)

    def _search(self, keywords=None, symbols=None, maxhits=None,
                startdate=None, enddate=None, **kwargs):
        if not keywords and not symbols:
            raise ValueError('Either keywords or symbols are required')

        data = {}

        if keywords:
            if isinstance(keywords, types.StringTypes):
                keywords = [keywords]

            data['keywords'] = ','.join(keywords)

        if symbols:
            if isinstance(symbols, types.StringTypes):
                symbols = [symbols]

            data['symbols'] = ','.join(symbols)

        if maxhits:
            data['maxhits'] = maxhits

        # TODO(jkoelker) calculate enddate to be now()
        if (not startdate and enddate) or (not enddate and startdate):
            raise ValueError('Both startdate and endate are required if one '
                             'is specified')

        if startdate and enddate:
            data['startdate'] = startdate
            data['enddate'] = enddate

        path = self._api.join(BASE_URL, 'market', 'news', 'search')
        return self._api.post(path, data=data, **kwargs)

    def article(self, article_id):
        r = self._article(article_id=article_id)
        return r['response']['article']

    def search(self, keywords=None, symbols=None, maxhits=None, startdate=None,
               enddate=None):
        r = self._search(keywords=keywords, symbols=symbols, maxhits=maxhits,
                         startdate=startdate, enddate=enddate)
        return r['response']['articles']['article']


class Options(object):
    def __init__(self, api):
        self._api = api

    symbol = staticmethod(option_symbol)

    def _expirations(self, symbol, **kwargs):
        params = {'symbol': symbol}
        path = self._api.join(BASE_URL, 'market', 'options', 'expirations')
        return self._api.get(path, params=params, **kwargs)

    def _search(self, symbol, query, fields=None, query_is_prepared=False,
                **kwargs):
        if not isinstance(query, OptionQuery) and not query_is_prepared:
            query = OptionQuery(query)

        data = {'symbol': symbol, 'query': query}

        if fields is not None:
            data['fids'] = ','.join(fields)

        path = self._api.join(BASE_URL, 'market', 'options', 'search')
        return self._api.post(path, data=data, **kwargs)

    def _strikes(self, symbol, **kwargs):
        params = {'symbol': symbol}
        path = self._api.join(BASE_URL, 'market', 'options', 'strikes')
        return self._api.get(path, params=params, **kwargs)

    def expirations(self, symbol):
        r = self._expirations(symbol=symbol)
        expirations = r['response']['expirationdates']['date']
        return pd.to_datetime(pd.Series(expirations))

    def search(self, symbol, query, fields=None):
        r = self._search(symbol=symbol, query=query, fields=fields)
        return _quotes_to_df(r['response']['quotes']['quote'])

    def strikes(self, symbol):
        r = self._strikes(symbol=symbol)
        strikes = r['response']['prices']['price']
        return pd.Series(strikes, dtype=float)


class Market(object):
    def __init__(self, api):
        self._api = api

    def _clock(self, **kwargs):
        path = self._api.join(BASE_URL, 'market', 'clock')
        return self._api.get(path, **kwargs)

    def _quotes(self, symbols, fields=None, **kwargs):
        if isinstance(symbols, (types.ListType, types.TupleType)):
            symbols = ','.join(symbols)

        params = {'symbols': symbols}

        if fields is not None:
            params['fids'] = ','.join(fields)

        path = self._api.join(BASE_URL, 'market', 'ext', 'quotes')
        return self._api.get(path, params=params, **kwargs)

    def _toplist(self, list_type='toppctgainers', **kwargs):
        path = self._api.join(BASE_URL, 'market', 'toplists', list_type)
        return self._api.get(path, **kwargs)

    @property
    def clock(self):
        r = self._clock()
        r = r['response']
        del r['@id']
        return r

    @utils.cached_property(ttl=0)
    def news(self):
        return News(self._api)

    @utils.cached_property(ttl=0)
    def options(self):
        return Options(self._api)

    def quotes(self, symbols, fields=None):
        r = self._quotes(symbols=symbols, fields=fields)
        return _quotes_to_df(r['response']['quotes']['quote'])

    def toplist(self, list_type='toppctgainers'):
        r = self._toplist(list_type=list_type)
        return _quotes_to_df(r['response']['quotes']['quote'])

    # TODO(jkoelker) market/timesales
    # TODO(jkoelker) market/quotes (iterator)


class TradeKing(object):
    def __init__(self, consumer_key, consumer_secret,
                 oauth_token, oauth_secret):
        self._api = API(consumer_key=consumer_key,
                        consumer_secret=consumer_secret,
                        oauth_token=oauth_token,
                        oauth_secret=oauth_secret)

    def _accounts(self, **kwargs):
        path = urlparse.urljoin(BASE_URL, 'accounts')
        return self._api.get(path, **kwargs)

    def account(self, account_id):
        return Account(self._api, account_id)

    @utils.cached_property(ttl=0)
    def market(self):
        return Market(self._api)

    # TODO(jkoelker) member/profile
    # TODO(jkoelker) utility/status
    # TODO(jkoelker) utility/version
    # TODO(jkoelker) utility/version
    # TODO(jkoelker) watchlists
