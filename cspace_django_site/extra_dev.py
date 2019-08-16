# settings needed for Development

try:
    # get the tracking id for Dev
    from cspace_django_site.trackingids import trackingids
    UA_TRACKING_ID = trackingids['webapps-dev'][0]
except:
    print('UA tracking ID not found for Development. It should be "webapps-dev" in "trackingids.py"')
    exit(0)

DEBUG = True
TEMPLATE_DEBUG = DEBUG

# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/2.2/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ['*']
