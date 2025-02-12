# -*- coding: UTF-8 -*-
import re
import time, datetime
import csv
import solr
import html
import os
import logging

from os import path, popen
from copy import deepcopy
from cspace_django_site import settings
from common.cspace import getConfig

from io import BytesIO
# disable reportlab code for now
# from common.table import makeReport
from django.http import HttpResponse, HttpResponseRedirect

SolrIsUp = True  # an initial guess! this is verified below...

# Get an instance of a logger
logger = logging.getLogger(__name__)


def loginfo(webapp, infotype, context, request):
    if webapp: pass
    logdata = ''
    # user = getattr(request, 'user', None)
    try:
    #if request.user and not request.user.is_anonymous():
        username = request.user.username
    #else:
    except:
        username = '-'
    if 'count' in context:
        count = context['count']
    else:
        count = '-'
    if 'querystring' in context:
        logdata = context['querystring']
    if 'url' in context:
        logdata += ' url: %s' % context['url']
    if 'elapsed_time' in context:
        logdata += ' elapsed_time: %s' % context['elapsed_time']
    logger.info('%s :: %s :: %s :: %s :: %s' % (webapp, infotype, count, username, logdata))


def getfromXML(element, xpath):
    result = element.find(xpath)
    if result is None: return ''
    result = '' if result.text is None else result.text
    result = re.sub(r"^.*\)'(.*)'$", "\\1", result)
    return result


def deURN(string):
    # replace all occurrences of refnames in string with displayName chunk
    return re.sub(r"urn:.*?'(.*?)'", r'\1', string)


def getfields(fieldset, pickField, prmz):
    result = []
    pickField = pickField.split(',')
    for pick in pickField:
        if not pick in 'name solrfield label'.split(' '):
            pick = 'solrfield'
        result.append([f[pick] for f in prmz.FIELDS[fieldset] if f['fieldtype'] not in ['constant', 'subheader']])
    if len(pickField) > 1:
        # is this right??
        return list(zip(result[0], result[1]))
    else:
        return result[0]


def getfacets(response):
    # facets = response.get('facet_counts').get('facet_fields')
    facets = response.facet_counts
    facets = facets['facet_fields']
    _facets = {}
    for key, values in facets.items():
        _v = []
        for k, v in values.items():
            _v.append((k, v))
        _facets[key] = sorted(_v, key=lambda ab: (ab[1]), reverse=True)
    return _facets


def parseTerm(queryterm):
    queryterm = queryterm.strip(' ')
    terms = queryterm.split(' ')
    terms = ['"' + t + '"' for t in terms]
    result = ' AND '.join(terms)
    if 'AND' in result: result = '(' + result + ')'  # we only need to wrap the query if it has multiple terms
    return result


def makeMarker(location):
    if location:
        location = location.replace(' ', '')
        latitude, longitude = location.split(',')
        latitude = float(latitude)
        longitude = float(longitude)
        return "%0.2f,%0.2f" % (latitude, longitude)
    else:
        return None


def checkValue(cell):
    try:
        return str(cell)
    except:
        print('unicode problem', cell.encode('utf-8', 'ignore'))
        return cell.encode('utf-8', 'ignore')


def writeCsv(filehandle, fieldset, items, writeheader=False, csvFormat='csv'):
    # loginfo('search', "Fieldset: %s" % fieldset, {}, {})
    writer = csv.writer(filehandle, delimiter='\t')
    # write the header
    if writeheader:
        writer.writerow(fieldset)
    for item in items:
        # get the cells from the item dict in the order specified; make empty cells if key is not found.
        row = []
        if csvFormat == 'bmapper':
            r = []
            for x in item['otherfields']:
                if x['name'] not in fieldset:
                    continue
                if type(x['value']) == type([]):
                    x['value'] = '|'.join(x['value'])
                    pass
                r.append(checkValue(x['value']))
            location = item['location']
            l = location.split(',')
            r.append(l[0])
            r.append(l[1])
            for cell in r:
                row.append(cell)
        elif csvFormat == 'statistics':
            row.append(checkValue(item[0]))  # summarizeon
            row.append(checkValue(item[1]))  # count
            for x in item[2]:
                if type(x) == type([]):
                    x = '|'.join(x)
                    pass
                cell = checkValue(x)
                row.append(cell)
        else:
            for x in item['otherfields']:
                if x['name'] not in fieldset:
                    continue
                if type(x['value']) == type([]):
                    x['value'] = '|'.join(x['value'])
                    pass
                cell = checkValue(x['value'])
                row.append(cell)
        row = [r.encode('ascii', 'xmlcharrefreplace').decode('ascii') for r in row]
        writer.writerow(row)
    return filehandle

def getMapPoints(context, requestObject):
    mappableitems = []
    if 'select-items' in requestObject:
        mapitems = context['items']
        numSelected = len(mapitems)
    else:
        selected = []
        for p in requestObject:
            if 'item-' in p:
                selected.append(requestObject[p])
        numSelected = len(selected)
        mapitems = []
        for item in context['items']:
            if item['csid'] in selected:
                mapitems.append(item)
    for item in mapitems:
        try:
            m = makeMarker(item['location'])
            if m is not None:
                mappableitems.append(item)
        except KeyError:
            pass
    return mappableitems, numSelected


def setupGoogleMap(request, requestObject, context, prmz):
    context = doSearch(context, prmz, request)
    selected = []
    for p in requestObject:
        if 'item-' in p:
            selected.append(requestObject[p])
    mappableitems = []
    markerlist = []
    markerlength = 200
    for item in context['items']:
        if item['csid'] in selected:
            # if True:
            try:
                m = makeMarker(item['location'])
                if markerlength > 2048: break
                if m is not None:
                    markerlist.append(m)
                    mappableitems.append(item)
                    markerlength += len(m) + 8  # 8 is the length of '&markers='
            except KeyError:
                pass
    context['mapmsg'] = []
    if len(context['items']) < context['count']:
        context['mapmsg'].append('%s points plotted. %s selected objects examined (of %s in result set).' % (
            len(markerlist), len(selected), context['count']))
    else:
        context['mapmsg'].append(
            '%s points plotted. all %s selected objects in result set examined.' % (len(markerlist), len(selected)))
    context['items'] = mappableitems
    context['markerlist'] = '&markers='.join(markerlist)
    # context['markerlist'] = '&markers='.join(markerlist[:MAXMARKERS])

    # if len(markerlist) >= MAXMARKERS:
    #    context['mapmsg'].append(
    #        '%s points is the limit. Only first %s accessions (with latlongs) plotted!' % (MAXMARKERS, len(markerlist)))

    return context


def setupBMapper(request, requestObject, context, prmz):
    context['berkeleymapper'] = 'set'
    context = doSearch(context, prmz, request)
    mappableitems, numSelected = getMapPoints(context, requestObject)
    context['mapmsg'] = []
    filename = 'bmapper%s.csv' % datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filehandle = open(path.join(prmz.LOCALDIR, filename), 'w')
    writeCsv(filehandle, getfields('bMapper', 'name', prmz), mappableitems, writeheader=False, csvFormat='bmapper')
    filehandle.close()
    context['mapmsg'].append('%s points of the %s selected objects examined had latlongs (%s in result set).' % (
        len(mappableitems), numSelected, context['count']))
    # context['mapmsg'].append('if our connection to berkeley mapper were working, you be able see them plotted there.')
    context['items'] = mappableitems
    bmapperconfigfile = '%s/%s/%s' % (prmz.BMAPPERSERVER, prmz.BMAPPERDIR, prmz.BMAPPERCONFIGFILE)
    tabfile = '%s/%s/%s' % (prmz.BMAPPERSERVER, prmz.BMAPPERDIR, filename)
    context['bmapperurl'] = prmz.BMAPPERURL % (tabfile, bmapperconfigfile)
    return context
    # return HttpResponseRedirect(context['bmapperurl'])

def makePlacemark(placename, longitude, latitude, altitude):

    return """<Placemark>
    <name>%s</name>
    <visibility>0</visibility>
    <LookAt>
    <longitude>%s</longitude>
    <latitude>%s</latitude>
    <altitude>%s</altitude>
    <heading>0</heading>
    <tilt>0</tilt>
    <range>7500.000000000000</range>
    <gx:altitudeMode>relativeToSeaFloor</gx:altitudeMode>
    </LookAt>
    <styleUrl>#s_ylw-pushpin82</styleUrl>
    <Point>
    <gx:drawOrder>1</gx:drawOrder>
    <coordinates>%s,%s,%s</coordinates>
    </Point>
    </Placemark>""" % (placename, longitude, latitude, altitude, longitude, latitude, altitude)

def setupKML(request, requestObject, context, prmz):

    context['berkeleymapper'] = 'set'
    context = doSearch(context, prmz, request)
    mappableitems, numSelected = getMapPoints(context, requestObject)
    context['mapmsg'] = []
    filename = 'kml-%s.kml' % datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    #filehandle = open(path.join(prmz.LOCALDIR, filename), 'w')
    response = HttpResponse(content_type='application/kml')
    response.write("""
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2" xmlns:kml="http://www.opengis.net/kml/2.2" xmlns:atom="http://www.w3.org/2005/Atom">
<Document>
        <name>KmlFile</name>
        <Style id="s_ylw-pushpin82">
                <IconStyle>
                        <scale>1.2</scale>
                        <Icon>
                                <href>http://maps.google.com/mapfiles/kml/shapes/donut.png</href>
                        </Icon>
                </IconStyle>
        </Style>
        <Style id="s_ylw-pushpin_hl91">
                <IconStyle>
                        <scale>1.4</scale>
                        <Icon>
                                <href>http://maps.google.com/mapfiles/kml/shapes/donut.png</href>
                        </Icon>
                </IconStyle>
        </Style>
        <StyleMap id="m_ylw-pushpin10">
                <Pair>
                        <key>normal</key>
                        <styleUrl>#s_ylw-pushpin82</styleUrl>
                </Pair>
                <Pair>
                        <key>highlight</key>
                        <styleUrl>#s_ylw-pushpin_hl91</styleUrl>
                </Pair>
        </StyleMap>
""")

    for i in mappableitems:
        (long,lat) = i['location'].split(',')
        try:
            place = i['otherfields']['fcp'].split(',')
            place = i[0]
        except:
            place = 'X'
        response.write(makePlacemark(place, lat, long, '0'))

    response.write("""
        </Document>
        </kml>""")
    context['mapmsg'].append('%s points of the %s selected objects examined had latlongs (%s in result set).' % (
        len(mappableitems), numSelected, context['count']))
    # context['mapmsg'].append('if our connection to berkeley mapper were working, you be able see them plotted there.')
    response['Content-Disposition'] = 'attachment; filename="%s"' % filename
    return response


def setup4PDF(request, context, prmz):
    csvformat, fieldset, csvitems = setupCSV(request, context, prmz)
    table = []
    table.append(context['fields'])
    for r in context['items']:
        row = []
        for f in r['otherfields']:
            if type(f['value']) == type([]):
                row.append(', '.join(f['value']))
            else:
                row.append(f['value'])
        table.append(row)

    # create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="%s-%s.%s"' % (
        prmz.CSVPREFIX, datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"), 'pdf')

    # Create the HttpResponse object with the appropriate PDF headers.
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="test.pdf"'

    buffer = BytesIO()

    # report = makeReport(buffer, 'Letter', 'header', 'footer')
    # pdf = report.fillReport(table)

    # response.write(pdf)
    return response


def setup4Print(request, context, prmz):
    return


def computeStats(request, requestObject, context, prmz):
    context['summarizeonlabel'] = prmz.PARMS[requestObject['summarizeon']][0]
    context['summarizeon'] = requestObject['summarizeon']
    context['summaryrows'] = [requestObject[z] for z in requestObject if 'include-' in z]
    context['summarylabels'] = [prmz.PARMS[var][0] for var in context['summaryrows']]
    context = doSearch(context, prmz, request)
    return context


def setupCSV(request, requestObject, context, prmz):
    if 'downloadstats' in requestObject:
        context = computeStats(request, requestObject, context, prmz)
        csvitems = context['summaryrows']
        format = 'statistics'
    else:
        format = 'csv'
        context = doSearch(context, prmz, request)
        selected = []
        # check to see if 'select all' is clicked...if so, skip checking individual items
        if 'select-items' in requestObject:
            csvitems = context['items']
        else:
            for p in requestObject:
                if 'item-' in p:
                    selected.append(requestObject[p])
            csvitems = []
            for item in context['items']:
                if item['csid'] in selected:
                    csvitems.append(item)

    if 'downloadstats' in requestObject:
        fieldset = [context['summarizeonlabel'], 'N'] + context['summarylabels']
    else:
        fieldset = getfields('inCSV', 'name', prmz)

    return format, fieldset, csvitems


def setDisplayType(requestObject, prmz):
    displayType = prmz.DEFAULTDISPLAY
    # a silly oversight has the parameter as 'displayType' in older portals, and 'displaytype' in the current one
    if   'displayType' in requestObject: displayType = requestObject['displayType']
    elif 'displaytype' in requestObject: displayType = requestObject['displaytype']
    if displayType == 'search-default':
        displayType = prmz.DEFAULTDISPLAY
    for value, label in prmz.BUTTONOPTIONS:
        if ('search-%s' % value) in requestObject:
            displayType = value
            break

    return displayType


def extractValue(listItem, key):
    # make all arrays into strings for display
    if key in listItem:
        if type(listItem[key]) == type([]):
            temp = ', '.join(listItem[key])
        else:
            temp = listItem[key]
    else:
        temp = ''

    # handle dates (convert them to collatable strings)
    if isinstance(temp, datetime.date):
        try:
            # item[p] = item[p].toordinal()
            temp = temp.isoformat().replace('T00:00:00+00:00', '')
        except:
            print('date problem: ', temp)

    return temp


def setConstants(context, prmz, request):
    if not SolrIsUp: context['errormsg'] = 'Solr is down!'
    context['suggestsource'] = prmz.SUGGESTIONS
    context['title'] = prmz.TITLE
    context['apptitle'] = prmz.TITLE
    context['imageserver'] = prmz.IMAGESERVER
    context['cspaceserver'] = prmz.CSPACESERVER
    context['institution'] = prmz.INSTITUTION
    context['emailableurl'] = prmz.EMAILABLEURL
    context['version'] = prmz.VERSION
    # context['layout'] = prmz.LAYOUT
    context['dropdowns'] = prmz.FACETS
    context['derivativecompact'] = prmz.DERIVATIVECOMPACT
    context['derivativegrid'] = prmz.DERIVATIVEGRID
    context['sizecompact'] = prmz.SIZECOMPACT
    context['sizegrid'] = prmz.SIZEGRID
    context['resultlimit'] = prmz.MAXRESULTS
    context['timestamp'] = time.strftime("%b %d %Y %H:%M:%S", time.localtime())
    context['qualifiers'] = [{'val': s, 'dis': s} for s in prmz.SEARCH_QUALIFIERS]
    context['resultoptions'] = [50, 100, 500, 1000, 2000, 10000]
    context['csrecordtype'] = prmz.CSRECORDTYPE
    context['buttonoptions'] = prmz.BUTTONOPTIONS
    context['defaultdisplay'] = prmz.DEFAULTDISPLAY


    context['searchrows'] = range(prmz.SEARCHROWS + 1)[1:]
    context['searchcolumns'] = range(prmz.SEARCHCOLUMNS + 1)[1:]

    emptyCells = {}
    for row in context['searchrows']:
        for col in context['searchcolumns']:
            empty = True
            for field in prmz.FIELDS['Search']:
                if field['row'] == row and field['column'] == col:
                    empty = False
            if empty:
                if not row in emptyCells:
                    emptyCells[row] = {}
                emptyCells[row][col] = 'X'
    context['emptycells'] = emptyCells

    # copy over form values to context if they exist
    try:
        requestObject = context['searchValues']

        # build a list of the search term qualifiers used in this query (for templating...)
        qualfiersInUse = []
        for formkey, formvalue in requestObject.items():
            if '_qualifier' in formkey:
                qualfiersInUse.append(formkey + ':' + formvalue)

        context['qualfiersInUse'] = qualfiersInUse

        context['displayType'] = setDisplayType(requestObject, prmz)
        if 'url' in requestObject: context['url'] = requestObject['url']
        if 'querystring' in requestObject: context['querystring'] = requestObject['querystring']
        if 'core' in requestObject: context['core'] = requestObject['core']
        if 'pixonly' in requestObject: context['pixonly'] = requestObject['pixonly']
        context['maxresults'] = int(requestObject['maxresults']) if 'maxresults' in requestObject else context['resultoptions'][0]
        context['start'] = int(requestObject['start']) if 'start' in requestObject else 1
        context['maxfacets'] = int(requestObject['maxfacets']) if 'maxfacets' in requestObject else prmz.MAXFACETS
        context['sortkey'] = requestObject['sortkey'] if 'sortkey' in requestObject else prmz.DEFAULTSORTKEY
    except:
        loginfo('search', "no searchValues set", context, request)
        context['displayType'] = setDisplayType({}, prmz)
        context['url'] = ''
        context['querystring'] = ''
        context['core'] = prmz.SOLRCORE
        context['maxresults'] = context['resultoptions'][0]
        context['start'] = 1
        context['sortkey'] = prmz.DEFAULTSORTKEY

    if context['start'] < 1: context['start'] = 1

    context['PARMS'] = prmz.PARMS
    if not 'FIELDS' in context:
        context['FIELDS'] = prmz.FIELDS

    # set defaults first time through
    for searchfield in prmz.FIELDS['Search']:
        if 'default' in searchfield['fieldtype']:
            searchfield['value'] = searchfield['fieldtype'][2]
            searchfield['fieldtype'] = searchfield['fieldtype'][0]

    context['device'] = devicetype(request)

    try:
        alert_config = getConfig(os.path.join(settings.BASE_DIR, 'config'), 'alert')
        context['ALERT'] = alert_config.get('alert', 'ALERT')
        context['MESSAGE'] = alert_config.get('alert', 'MESSAGE')
    except:
        x = settings.BASE_DIR
        context['ALERT'] = ''

    return context


def generate_query_term(t, p, prmz, requestObject, context):
    # loginfo('search', 'qualifier:',requestObject[p+'_qualifier'], context, request)
    index = prmz.PARMS[p][3]
    # if this is a "switcharoo field", use the specified shadow
    if prmz.PARMS[p][6] != '':
        index = prmz.PARMS[p][6]
    qualifier = requestObject[p + '_qualifier']
    if qualifier == 'exact':
        # for exact searches, reset the index to the original in case the switcharoo changed it
        index = prmz.PARMS[p][3]
        index = index.replace('_txt', '_s')
        # only our own double quotes are unescaped
        t = t.replace('"', '\\"')
        t = '"' + t + '"'
    elif qualifier == 'phrase':
        index = index.replace('_ss', '_txt').replace('_s', '_txt')
        # only our own double quotes are unescaped
        t = t.replace('"', '\\"')
        t = '"' + t + '"'
    elif qualifier == 'keyword':
        # eliminate some characters that might confuse solr's query parser
        t = re.sub(r'[\[\]\:\(\)\" ]', ' ', t).strip()
        # hyphen is allowed, but only as a negation operator
        t = re.sub(r'([^ ])-', r'\1 ', ' ' + t).strip()
        # get rid of muliple spaces in a row
        t = re.sub(r' +', ' ', t)
        t = t.split(' ')
        t = ' +'.join(t)
        t = '(+' + t + ')'
        t = t.replace('+-', '-')  # remove the plus if user entered a minus
        index = index.replace('_ss', '_txt').replace('_s', '_txt')
    return t, index


def devicetype(request):
    # http://blog.mobileesp.com/
    # the middleware must be installed for the following to work...
    try:
        if request.is_phone:
            return 'phone'
        elif request.is_tablet:
            return 'tablet'
        else:
            return 'other'
    except:
        return 'other'


def doSearch(context, prmz, request):
    elapsedtime = time.time()
    solr_server = prmz.SOLRSERVER
    solr_core = prmz.SOLRCORE
    context = setConstants(context, prmz, request)
    requestObject = context['searchValues']

    formFields = deepcopy(prmz.FIELDS)
    for searchfield in formFields['Search']:
        if searchfield['name'] in requestObject.keys():
            searchfield['value'] = requestObject[searchfield['name']]
        else:
            searchfield['value'] = ''

    context['FIELDS'] = formFields

    # create a connection to a solr server
    s = solr.SolrConnection(url='%s/%s' % (solr_server, solr_core))
    queryterms = []
    urlterms = []

    if 'berkeleymapper' in context:
        displayFields = 'bMapper'
    elif 'csv' in requestObject:
        displayFields = 'inCSV'
    else:
        displayFields = context['displayType'] + 'Display'

    facetfields = getfields('Facet', 'solrfield', prmz)
    if 'summarize' in requestObject or 'downloadstats' in requestObject:
        solrfl = [prmz.PARMS[p][3] for p in context['summaryrows']]
        solrfl.append(prmz.PARMS[context['summarizeon']][3])
    else:
        solrfl = getfields(displayFields, 'solrfield', prmz)
    solrfl += prmz.REQUIRED  # always get these
    if 'map-google' in requestObject or 'csv' in requestObject or 'pdf' in requestObject or 'map-kml' in requestObject or 'map-bmapper' in requestObject or 'summarize' in requestObject or 'downloadstats' in requestObject or 'special' in requestObject:
        querystring = requestObject['querystring']
        url = requestObject['url']
        # Did the user request the full set?
        if 'select-items' in requestObject:
            context['maxresults'] = prmz.MAXRESULTS
            context['start'] = 1
    else:
        for p in requestObject:
            # skip form values that are not strictly input values
            if p in ['csrfmiddlewaretoken', 'displayType', 'displaytype', 'resultsOnly', 'maxresults', 'url', 'querystring', 'pane',
                     'pixonly', 'locsonly', 'acceptterms', 'submit', 'start', 'sortkey', 'count', 'summarizeon',
                     'summarize', 'summaryfields', 'lastpage', 'score', 'right', 'wrong']: continue
            if p == '_': continue
            if '_qualifier' in p: continue
            if 'select-' in p: continue  # skip select control for map markers
            if 'include-' in p: continue  # skip form values used in statistics
            if 'item-' in p: continue
            if not requestObject[p]: continue  # uh...looks like we can have empty items...let's skip 'em
            searchTerm = requestObject[p]
            terms = searchTerm.split(' OR ')
            ORs = []
            querypattern = '%s:%s'  # default search expression pattern (dates are different)
            for t in terms:
                t = t.strip()
                # handle range search
                if ' TO ' in t:
                    try:
                        qualifier = requestObject[p + '_qualifier']
                    except:
                        qualifier = 'exact'
                    # range searching on keywords is ... kinda meaningless in our context, at least
                    if qualifier == 'keyword':
                        qualifier = 'phrase'
                    to_terms = t.split(' TO ')
                    to_terms = [generate_query_term(x, p, prmz, {p + '_qualifier': qualifier}, context)[0] for x in to_terms]
                    dummy, index = generate_query_term(t, p, prmz, {p + '_qualifier': qualifier}, context)
                    try:
                        t = '[%s TO %s]' % tuple(to_terms)
                    except:
                        t = '[%s]' % t
                elif t == 'Null':
                    t = '[* TO *]'
                    index = '-' + prmz.PARMS[p][3]
                # if we are testing for 'presence' or 'absence', this is handled elsewhere
                elif prmz.PARMS[p][1] == 'present':
                    if t == 'yes':
                        index = prmz.PARMS[p][3]
                    else:
                        index = '-' + prmz.PARMS[p][3]
                    if '_p' in prmz.PARMS[p][3]:
                        t = "[-90,-180 TO 90,180]"
                    else:
                        t = '[* TO *]'
                else:
                    if p in prmz.DROPDOWNS:
                        # if it's a value in a dropdown, it must always be an "exact search"
                        # only our own double quotes are unescaped
                        t = t.replace('"', '\\"')
                        t = '"' + t + '"'
                        index = prmz.PARMS[p][3].replace('_txt', '_s')
                    elif p + '_qualifier' in requestObject:
                        t, index = generate_query_term(t, p, prmz, requestObject, context)
                    elif '_dt' in prmz.PARMS[p][3]:
                        querypattern = '%s: "%sZ"'
                        index = prmz.PARMS[p][3]
                    else:
                        # if no search qualifier is specified use the 'phrase' approach, copied from above
                        # eliminate some characters that might confuse solr's query parser
                        index = prmz.PARMS[p][3]
                        # index = index.replace('_ss', '_txt').replace('_s', '_txt')
                        # escape funny characters
                        t = re.sub(r'([\[\]\:\(\)\")\-\. ])', r'\\\g<1>', t)
                        # t = '"' + t + '"'
                if t == 'OR': t = '"OR"'
                if t == 'AND': t = '"AND"'
                ORs.append(querypattern % (index, t))
            searchTerm = ' OR '.join(ORs)
            if ' ' in searchTerm and not ' TO ' in searchTerm: searchTerm = ' (' + searchTerm + ') '
            queryterms.append(searchTerm)
            urlterms.append('%s=%s' % (p, html.escape(requestObject[p])))
            if p + '_qualifier' in requestObject:
                # print('qualifier:',requestObject[p+'_qualifier'])
                urlterms.append('%s=%s' % (p + '_qualifier', html.escape(requestObject[p + '_qualifier'])))
        querystring = ' AND '.join(queryterms)

        if urlterms != []:
            urlterms.append('displayType=%s' % context['displayType'])
            urlterms.append('maxresults=%s' % context['maxresults'])
            urlterms.append('start=%s' % context['start'])

            if 'summarize' in requestObject or 'downloadstats' in requestObject:
                urlterms.append('summarize=%s' % context['summarizeon'])
                urlterms.append('summaryfields=%s' % ','.join(context['summaryrows']))
        url = '&'.join(urlterms)

    if 'pixonly' in context:
        pixonly = context['pixonly']
        querystring += " AND %s:[* TO *]" % prmz.PARMS['blobs'][3]
        url += '&pixonly=True'
    else:
        pixonly = None

    if 'locsonly' in requestObject:
        locsonly = requestObject['locsonly']
        querystring += " AND %s:[-90,-180 TO 90,180]" % prmz.LOCATION
        url += '&locsonly=True'
    else:
        locsonly = None

    try:
        startpage = context['maxresults'] * (context['start'] - 1)
    except:
        startpage = 0
        context['start'] = 1

    loginfo('search', 'query: %s' % querystring, context, request)
    try:
        solrtime = time.time()
        # TODO: this hack allows keyword searching while continuing to use the _s versions in displays
        solrfl2 = [ sf.replace('_txt','_s') for sf in solrfl ]
        response = s.query(querystring, facet='true', facet_field=facetfields, fq={}, fields=solrfl2,
                           rows=context['maxresults'], facet_limit=prmz.MAXFACETS, sort=context['sortkey'],
                           facet_mincount=1, start=startpage)
        loginfo('search', 'Solr search succeeded, %s results, %s rows requested starting at %s; %8.2f seconds.' % (response.numFound, context['maxresults'], startpage, time.time() - solrtime), context, request)
    # except:
    except Exception as inst:
        # raise
        loginfo('search', 'Solr search failed: %s' % str(inst), context, request)
        context['errormsg'] = 'Solr4 query failed'
        return context

    results = response.results

    context['items'] = []
    summaryrows = {}
    imageCount = {'cards': 0, 'blobs': 0}
    for i, rowDict in enumerate(results):
        item = {}
        item['counter'] = i

        if 'summarize' in requestObject or 'downloadstats' in requestObject:
            summarizeon = extractValue(rowDict, prmz.PARMS[context['summarizeon']][3])
            summfields = [extractValue(rowDict, prmz.PARMS[p][3]) for p in context['summaryrows']]
            if not summarizeon in summaryrows:
                x = []
                for ii in range(len(context['summaryrows'])): x.append([])
                summaryrows[summarizeon] = [0, deepcopy(x)]
            for sumi, sumcol in enumerate(summfields):
                if not sumcol in summaryrows[summarizeon][1][sumi]:
                    summaryrows[summarizeon][1][sumi] += [sumcol, ]
                    # loginfo('search', summarizeon, sumi, sumcol, summaryrows[summarizeon][1][sumi], context, request)
            summaryrows[summarizeon][0] += 1

        # pull out the fields that have special functions in the UI
        for p in prmz.PARMS:
            # note please: there is no if-elif construction here...it is possible, for example
            # for the mainentry and the sortkey to be the same field!
            if 'sortkey' in prmz.PARMS[p][1]:
                item['sortkey'] = extractValue(rowDict, prmz.PARMS[p][3])
            if 'mainentry' in prmz.PARMS[p][1]:
                item['mainentry'] = extractValue(rowDict, prmz.PARMS[p][3])
            if 'objectno' in prmz.PARMS[p][1]:
                item['objectno'] = extractValue(rowDict, prmz.PARMS[p][3])
            if 'accession' in prmz.PARMS[p][1]:
                item['accession'] = extractValue(rowDict, prmz.PARMS[p][3])
                item['accessionfield'] = prmz.PARMS[p][4]
            if 'csid' in prmz.PARMS[p][1]:
                item['csid'] = extractValue(rowDict, prmz.PARMS[p][3])
            # uh oh ... need to fix the blob v. blobs and card vs. cards naming someday...
            for image in ['card', 'blob']:
                if image in prmz.PARMS[p][1]:
                    # there may not be any blobs for this record...
                    try:
                        item['%ss' % image] = rowDict[prmz.PARMS[p][3]]
                    except:
                        item['%ss' % image] = []
                    imageCount['%ss' % image] += len(item['%ss' % image])

        if prmz.LOCATION in rowDict.keys():
            item['marker'] = makeMarker(rowDict[prmz.LOCATION])
            item['location'] = rowDict[prmz.LOCATION]

        otherfields = []
        for p in prmz.FIELDS[displayFields]:
            if p['fieldtype'] == 'constant':
                otherfields.append({'label': p['label'], 'name': p['name'], 'multi': 0, 'value': p['solrfield']})
            elif p['fieldtype'] == 'present':
                multi = 0
                if p['solrfield'] in rowDict and rowDict[p['solrfield']] != []:
                    value2use = 'yes'
                else:
                    value2use = 'no'
                otherfields.append({'label': p['label'], 'name': p['name'], 'multi': 0, 'value': value2use})
            elif p['solrfield'] in rowDict:
                value2use = rowDict[p['solrfield']]
                multi = len(rowDict[p['solrfield']]) if '_ss' in p['solrfield'] else 0
                if type(p['fieldtype']) == type([]) and p['fieldtype'][1] != 'default':
                    value2use = [p['fieldtype'][1][v] for v in value2use]
                    otherfields.append({'label': p['label'], 'name': p['name'], 'multi': multi, 'value': value2use, 'special': p['fieldtype'][0]})
                else:
                    otherfields.append({'label': p['label'], 'name': p['name'], 'multi': multi, 'value': value2use})
            else:
                otherfields.append({'label': p['label'], 'name': p['name'], 'multi': 0, 'value': ''})
        item['otherfields'] = otherfields
        context['items'].append(item)

    # if context['displayType'] in ['full', 'grid'] and response._numFound > prmz.MAXRESULTS:
    # context['recordlimit'] = '(limited to %s for long display.)' % prmz.MAXRESULTS
    #    context['items'] = context['items'][:prmz.MAXLONGRESULTS]
    if context['displayType'] in ['full', 'grid', 'list'] and response._numFound > context['maxresults']:
        context['recordlimit'] = '(display limited to %s.)' % context['maxresults']

    # I think this hack works for most values... but really it should be done properly someday... ;-)
    numberOfPages = 1 + int(response._numFound / (context['maxresults'] + 0.001))
    context['lastpage'] = numberOfPages
    context['pagesummary'] = 'Page %s of %s [items %s to %s]. ' % (
        context['start'], numberOfPages, startpage + 1,
        min(context['start'] * context['maxresults'], response._numFound))

    context['count'] = response._numFound

    m = {}
    for p in prmz.PARMS:
        m[prmz.PARMS[p][3]] = prmz.PARMS[p][4]

    facets = getfacets(response)
    context['labels'] = [p['label'] for p in prmz.FIELDS[displayFields]]
    context['facets'] = [[m[f], facets[f]] for f in facetfields]
    context['fields'] = getfields('Facet', 'label', prmz)
    context['statsfields'] = getfields('inCSV', 'name,label,solrfield', prmz)
    context['summaryrows'] = [[r, summaryrows[r][0], summaryrows[r][1]] for r in sorted(summaryrows.keys())]
    context['itemlisted'] = len(context['summaryrows'])
    context['range'] = range(len(facetfields))
    # context['pixonly'] = pixonly
    # context['locsonly'] = locsonly
    try:
        context['pane'] = requestObject['pane']
    except:
        context['pane'] = '0'
    try:
        context['resultsOnly'] = requestObject['resultsOnly']
    except:
        pass

    context['imagecount'] = imageCount['blobs']
    context['cardcount'] = imageCount['cards']
    context['url'] = url
    context['querystring'] = querystring
    context['core'] = solr_core
    context['time'] = '%8.3f' % (time.time() - elapsedtime)
    return context
