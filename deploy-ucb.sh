#!/bin/bash
# a helper for deploying the django webapps to ucb environments on rtl 'managed servers'
#
# while it does work, it is still rather primitive...
# ymmv! use it if it really helps!
#

VERSION=""  # Default to no version
ENVIRONMENT="pycharm" # Default to 'local dev' environment
WHOLE_LIST="bampfa botgarden cinefiles pahma ucjeps"

function usage() {
  echo
  echo "usage:"
  echo
  echo "./deploy_ucb.sh [-v VERSION] [-e {dev,prod,pycharm}] MUSEUM (or -a for all museums)"
  echo
  echo "to deploy a particular version for all ucb museums(i.e. tag):"
  echo "./deploy_ucb.sh -a -v 5.1.0-rc3 -e prod"
  echo
  echo "to deploy a particular version (i.e. tag) for pahma and cinefiles:"
  echo "./deploy_ucb.sh pahma -v 5.1.0-rc3 cinefiles -e dev"
  echo
  echo "nb: assumes you have the two needed repos set up in the standard RTL way."
  echo "    See the README.md in this repo for details."
  echo "    if no version is specified, this repo is copied and used as the source ... i.e. including"
  echo "    uncommitted changes. Good for testing!"
  echo "    if no runtime environment (-e) is specified, pycharm (i.e. local dev) is assumed"
  echo
  exit 0
}

if [[ $# -eq 0 ]] ; then
  usage
  exit 0
fi

while [[ $# -gt 0 ]] ;
do
  opt="$1";
  shift;
  case ${opt} in
    '-h' )
    usage
    ;;
    '-a' )
      MUSEUMS=$WHOLE_LIST
    ;;
    '-v' )
      VERSION=$1 ; shift;
    ;;
    '-e' )
      ENVIRONMENT=$1 ; shift
    ;;
    * )
    if [[ ! $MUSEUMS =~ .*$opt.* ]]
    then
        MUSEUMS="${MUSEUMS} $opt"
    fi
    ;;
  esac
done

echo "museums:     ${MUSEUMS}"
echo "environment: ${ENVIRONMENT}"
echo "version:     ${VERSION}"

cd ${HOME}/cspace-webapps-common/

# update bin directory
cp bin/* ${HOME}/bin

for t in $MUSEUMS
do
  ./setup.sh deploy "${t}" "${ENVIRONMENT}" "${VERSION}"
done
