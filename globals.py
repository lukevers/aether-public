# This file should not import any aether libraries!
# For some reason, if I import stuff here from main the app breaks. The frontend will just show a spinning beachball.
# But imports to all other places work fine.
from __future__ import print_function
import sys
from os import mkdir
import cPickle as pickle
import hashlib, random
import ujson
import subprocess
from shutil import copy
from twisted.internet.ssl import ContextFactory, ClientContextFactory
from OpenSSL import SSL, crypto
import os
import stat
import socket



# Current Running Platform: A lot of things depend on this.. Anything about the filesystem, adding to boot etc.

if sys.platform == 'darwin':
    PLATFORM = 'OSX'
elif sys.platform.startswith('win'):
    PLATFORM = 'WIN'
elif sys.platform.startswith('linux'):
    PLATFORM = 'LNX'
else:
    PLATFORM = 'UNKNOWN'
    raise Exception('AetherError: OS Type can not be determined.')

##print('Aether is running on %s' %PLATFORM)

# These define application status, either running on command line, or packaged into an app bundle.
if getattr(sys, 'frozen', False): # If this is a frozen PyInstaller bundle.
    FROZEN = True
    if PLATFORM == 'OSX':
        BASEDIR = sys._MEIPASS+'/'
        BASE_URL = BASEDIR
        PROFILE_DIR = os.path.expanduser('~/Library/Application Support/Aether/')
    elif PLATFORM == 'WIN':
        BASEDIR = sys._MEIPASS+'/'
        BASE_URL = BASEDIR
        PROFILE_DIR = os.environ['ALLUSERSPROFILE']+'\\Aether\\'
    elif PLATFORM == 'LNX':
        BASEDIR = sys._MEIPASS+'/'
        BASE_URL = BASEDIR
        PROFILE_DIR = os.path.expanduser('~/.aether/')

else: # If running on command line.
    FROZEN = False
    if PLATFORM == 'OSX':
        BASEDIR = ''
        PROFILE_DIR = os.path.expanduser('~/Library/Application Support/Aether/')
        BASE_URL = os.path.dirname(__file__)+'/'
    elif PLATFORM == 'WIN':
        BASEDIR =  ''
        PROFILE_DIR = os.environ['ALLUSERSPROFILE']+'\\Aether\\'
        BASE_URL = os.path.dirname(__file__)+'/'
    elif PLATFORM == 'LNX':
        BASEDIR = ''
        PROFILE_DIR = os.path.expanduser('~/.aether/')
        BASE_URL = os.path.dirname(__file__)+'/'

try:
    mkdir(PROFILE_DIR)
    mkdir(PROFILE_DIR + 'UserProfile')
    mkdir(PROFILE_DIR + 'Database')
    mkdir(PROFILE_DIR + 'Logs')
except: pass


# Application version.

AETHER_VERSION = 123

#Protocol Version of this version of the app. This is separate from app version.

PROT_VERSION = 100


# If the application is paused.

appIsPaused = False
# This is here because:
# 1) this is a value that needs to be set many times from the backend, and not at all from the frontend.
# 2) This is related to the current running instance of the app and should be reset at every start.
notificationShown = False

# These are packet counts (how many items go into one packet) for nodes and headers used in aetherProtocol.
# These aren't supposed to be user editable. This is something inherent in the protocol and dictated by AMP's 65536 byte
# limit per packet.

NODE_PACKET_COUNT = 10
HEADER_PACKET_COUNT = 10

## Settable statics

# Set this to true if the app received the open signal at boot, so I can hide the splash and the UI.as

APP_STARTED_AT_SYSTEM_STARTUP = False


# If database or userSettings does not exist, this is a first run.
NEWBORN = True if not os.path.exists(PROFILE_DIR + 'Database/aether.db') and \
                   not os.path.exists(PROFILE_DIR + 'UserProfile/UserProfile.json') else False

# If database exists but not settings, then it's a reset. In that case,
# I preserve the DB, and update the local node information. This is a restart button.
RESETTED = True if os.path.exists(PROFILE_DIR + 'Database/aether.db') and \
                 not os.path.exists(PROFILE_DIR + 'UserProfile/UserProfile.json') else False

# Database does not exist, but settings do.
NUKED = True if not os.path.exists(PROFILE_DIR + 'Database/aether.db') and \
                  os.path.exists(PROFILE_DIR + 'UserProfile/UserProfile.json') else False


class UserProfile(object):

    def __init__(self):

        # This is the internal state.
        self.__settingsAndProfile = {}
        self.loadFromFilesystem()

    def loadFromFilesystem(self):
        if os.path.isfile(PROFILE_DIR+'UserProfile/UserProfile.json'):
            # We already have a JSON file. Load the details from the file at the start.
            with open(PROFILE_DIR+'UserProfile/UserProfile.json', 'rb') as f:
                self.__settingsAndProfile = ujson.loads(f.read())

                # Check for old version.
                if 'selectedTopics' in self.__settingsAndProfile:
                    # This is a 1.1.2 JSON file. needs to be migrated.
                    migrationResult = self.__migrateFrom112to120(self.__settingsAndProfile)
                    with open(PROFILE_DIR+'UserProfile/UserProfile.json', 'wb') as f:
                        f.write(ujson.encode(migrationResult))
                    self.__settingsAndProfile = ujson.loads(f.read())
                else:
                    # The main
                    self.__updateBootStatus()
        else:
            # We don't have a JSON file. This means it's not created yet. Create it.
            with open(PROFILE_DIR+'UserProfile/UserProfile.json', 'wb') as f:
            # Now, time to set some defaults.
                newProfileFile = self.__produceProfileWithDefaults()
                newProfileFile['machineDetails']['listeningPort'] = self.__getRandomOpenPort()
                f.write(ujson.encode(newProfileFile))
            # This is the first load ever.
            with open(PROFILE_DIR+'UserProfile/UserProfile.json', 'rb') as f:
                self.__settingsAndProfile = ujson.loads(f.read())
            # Initialisation based on these values.




    def set(self, division, name, value):

        def __write(division, name, value):
            self.__settingsAndProfile[division][name] = value
            with open(PROFILE_DIR+'UserProfile/UserProfile.json', 'wb') as f:
                f.write(ujson.encode(self.__settingsAndProfile))

        try:
            self.__settingsAndProfile[division][name] = value
        except:
            self.loadFromFilesystem()
        else:
            print('Setting %s, %s as %s' %(division, name, str(value)))
            __write(division, name, value)

            # Special Cases. These cases require specific actions to be taken.
            if division == 'machineDetails':
                if name == 'startAtBoot':
                    self.__updateBootStatus()
            elif division == 'userDetails':
                pass
            elif division == 'debugDetails':
                pass

            with open(PROFILE_DIR+'UserProfile/UserProfile.json', 'wb') as f:
                f.write(ujson.encode(self.__settingsAndProfile))

    def get(self, division, name):
        self.loadFromFilesystem()
        try:
            result = self.__settingsAndProfile[division][name]
            print('Getting %s, %s, result is %s' %(division, name, str(self.__settingsAndProfile[division][name])))
        except KeyError:
            print('The application tried to reach a key that does not yet exist. Creating the JSON key.')
            self.set(division,name, None)
            result = None
        return result

    def __migrateFrom112to120(self, __old_profileJson):
        newTemplate = self.__produceProfileWithDefaults()

        # Extracting old values
        with open(PROFILE_DIR + 'UserProfile/backendSettings.dat', 'rb') as f:
            __old_nodeid = pickle.load(f)
            __old_enableWebkitInspector = pickle.load(f)
            __old_oldaetherListeningPort = pickle.load(f)
            __old_oldupdateAvailable = pickle.load(f)
            __old_onboardingComplete = pickle.load(f)
        __old_selectedTopics = __old_profileJson['selectedTopics']
        __old_username = __old_profileJson['UserDetails']['Username']
        __old_userLanguages = __old_profileJson['UserDetails']['UserLanguages']
        __old_startAtBoot = __old_profileJson['UserDetails']['StartAtBoot']
        __old_maxInboundCount = __old_profileJson['UserDetails']['maxInboundCount']
        __old_maxOutboundCount = __old_profileJson['UserDetails']['maxOutboundCount']
        __old_cooldown = __old_profileJson['UserDetails']['cooldown']
        __old_unreadReplies = __old_profileJson['UnreadReplies']
        __old_readReplies = __old_profileJson['ReadReplies']
        try:
            __old_subjectsSingleColumnLayout = __old_profileJson['subjectsSingleColumnLayout']
        except: pass # That may not always exist.

        # Putting in new values

        newTemplate['machineDetails']['maxOutboundCount'] = __old_maxOutboundCount
        newTemplate['machineDetails']['updateAvailable'] = __old_oldupdateAvailable
        newTemplate['machineDetails']['listeningPort'] = __old_oldaetherListeningPort
        newTemplate['machineDetails']['nodeid'] = __old_nodeid
        newTemplate['machineDetails']['startAtBoot'] = __old_startAtBoot
        newTemplate['machineDetails']['cooldown'] = __old_cooldown
        newTemplate['machineDetails']['cooldown'] = __old_cooldown
        newTemplate['machineDetails']['onboardingComplete'] = __old_onboardingComplete
        newTemplate['machineDetails']['maxInboundCount'] = __old_maxInboundCount

        newTemplate['userDetails']['username'] = __old_username
        newTemplate['userDetails']['unreadReplies'] = __old_unreadReplies
        try:
            newTemplate['userDetails']['subjectsSingleColumnLayout'] = __old_subjectsSingleColumnLayout
        except: pass
        newTemplate['userDetails']['readReplies'] = __old_readReplies
        newTemplate['userDetails']['userLanguages'] = __old_userLanguages
        newTemplate['userDetails']['selectedTopics'] = __old_selectedTopics

        newTemplate['debugDetails']['enableWebkitInspector'] = __old_enableWebkitInspector

        # And finally, remove the backendSettings.dat forever!
        os.remove(PROFILE_DIR + 'UserProfile/backendSettings.dat')

        return newTemplate

    def __produceProfileWithDefaults(self):
            userDetails = {
                'username': '',
                'userLanguages': ['English','Turkish','Spanish','French','German','Portuguese','Russian','Chinese','Chineset'],
                'selectedTopics': [],
                'readReplies': [],
                'unreadReplies': [],
                'subjectsSingleColumnLayout': False,
                'theme': False,
            }
            machineDetails = {
                'nodeid' : hashlib.sha256(str(random.getrandbits(256))).hexdigest(),
                'externalIP': '',
                'listeningPort': '',
                'updateAvailable': False,
                'onboardingComplete': False,
                'startAtBoot': True, # This is idempotent on Windows.
                'maxInboundCount': 3,
                'maxOutboundCount': 10,
                'cooldown': 5,
                'checkForUpdates': True,
                'allowPublicIPLookup': True,
                'lastConnectedBareIP': '',
                'lastConnectedBarePort': 0,
            }
            debugDetails = {
                'enableWebkitInspector': False,
                'debugLogging': False,
            }
            return { 'userDetails': userDetails,
                    'machineDetails': machineDetails,
                    'debugDetails':debugDetails, }

    def __getRandomOpenPort(self):
        # Binding to port 0 lets the OS give you an open port.
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.bind(("",0))
        s.listen(1)
        port = s.getsockname()[1]
        s.close()
        return port

    def __updateBootStatus(self):
        if FROZEN: # If not frozen, do nothing.
            if self.__settingsAndProfile['machineDetails']['startAtBoot']: # If at boot.
                if PLATFORM == 'OSX':
                    if not os.path.isfile(os.path.expanduser('~/Library/LaunchAgents/com.Aether.Aether.plist')):
                        try:
                            copy(BASEDIR+'Assets/com.Aether.Aether.plist',
                                 os.path.expanduser('~/Library/LaunchAgents/com.Aether.Aether.plist'))
                        except:
                            mkdir(os.path.expanduser('~/Library/LaunchAgents/'))
                            copy(BASEDIR+'Assets/com.Aether.Aether.plist',
                                 os.path.expanduser('~/Library/LaunchAgents/com.Aether.Aether.plist'))

                elif PLATFORM == 'WIN':
                    pass # On Windows, it's controlled by the OS, so this is idempotent.
                elif PLATFORM == 'LNX':
                    if not os.path.isfile(os.path.expanduser('~/.config/autostart/Aether-startup.desktop')):
                        try:
                            copy(BASEDIR+'Assets/Aether-startup.desktop',
                                os.path.expanduser('~/.config/autostart/Aether-startup.desktop'))
                            # Then set it to executable.
                        except:
                            mkdir(os.path.expanduser('~/.config/autostart/'))
                            copy(BASEDIR+'Assets/Aether-startup.desktop',
                                 os.path.expanduser('~/.config/autostart/Aether-startup.desktop'))
                        else:
                            st = os.stat(os.path.expanduser('~/.config/autostart/Aether-startup.desktop'))
                            os.chmod(os.path.expanduser('~/.config/autostart/Aether-startup.desktop'), st.st_mode | stat.S_IEXEC)

            else: # If the user decides to remove it.
                if PLATFORM == 'OSX':
                    try:
                        os.remove(os.path.expanduser('~/Library/LaunchAgents/com.Aether.Aether.plist'))
                    except: pass
                elif PLATFORM == 'WIN': # On Windows, it's controlled by the OS, so this is idempotent.
                    pass
                elif PLATFORM == 'LNX':
                    try:
                        os.remove(os.path.expanduser('~/.config/autostart/Aether-startup.desktop'))
                    except: pass

userProfile = UserProfile()


if not userProfile.get('debugDetails', 'debugLogging'):
    def print(*a, **kwargs):
        pass

if NEWBORN:
    print('This is the first run of Aether.')
elif RESETTED:
    print('Aether has just been resetted. Getting a new Node ID all settings are returned to defaults.')
elif NUKED:
    print('Aether has just been nuked. I\'m keeping the settings and Node ID, but creating a new database.')
    userProfile.set('machineDetails', 'onboardingComplete', False)

# This is the context factory used to create TLS contexts.

class AetherContextFactory(ContextFactory):
    def getContext(self):
        ctx = SSL.Context(SSL.TLSv1_METHOD)
        # This creates the key pairs and the cert if they do not exist.
        try:
            ctx.use_privatekey_file(PROFILE_DIR+'UserProfile/priv.pem')
            ctx.use_certificate_file(PROFILE_DIR+'UserProfile/cert.pem')
        except:
            # We don't have the requirements, so let's create them.
            ##print('This machine doesn\'nt seem to have a keypair and a cert. Creating new, at %s' %datetime.utcnow())
            k = crypto.PKey()
            k.generate_key(crypto.TYPE_RSA, 2048)
            cert = crypto.X509()
            cert.get_subject().countryName = 'XI'
            cert.get_subject().stateOrProvinceName = 'The Internet'
            cert.get_subject().localityName = 'Aether'
            cert.set_serial_number(1000)
            cert.gmtime_adj_notBefore(0)
            cert.gmtime_adj_notAfter(10*365*24*60*60)
            cert.set_issuer(cert.get_subject())
            cert.set_pubkey(k)
            cert.sign(k, 'sha1')
            newCertFile = open(PROFILE_DIR+'UserProfile/cert.pem', 'wb')
            newCertFile.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
            newCertFile.close()
            newKeyFile = open(PROFILE_DIR+'UserProfile/priv.pem', 'wb')
            newKeyFile.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
            newKeyFile.close()
            ##print('Key generation finished at %s' %datetime.utcnow())
            ctx.use_privatekey_file(PROFILE_DIR+'UserProfile/priv.pem')
            ctx.use_certificate_file(PROFILE_DIR+'UserProfile/cert.pem')

        return ctx

AetherClientContextFactory = ClientContextFactory

aetherClientContextFactoryInstance = AetherClientContextFactory()

aetherContextFactoryInstance = AetherContextFactory()

# Utility functions to provide basic functionality required in other parts of the application.

def checkIPValidity(address):
    if is_valid_ipv4_address(address) or is_valid_ipv6_address(address):
        return True
    return False

# Check if address is a valid IPv4 Address
def is_valid_ipv4_address(address):
    try:
        socket.inet_aton(address)
        return True
    except:
        return False

# Check if address is a valid IPv6 Address
def is_valid_ipv6_address(address):
    try:
        socket.inet_pton(socket.AF_INET6, address)
        return True
    except:
      return False

def logSystemDetails():
    # Print the system details.
    print('Running Aether %s with protocol version %s on %s' % (AETHER_VERSION, PROT_VERSION, PLATFORM))
    print('This is %s : %s at %s' % (
           userProfile.get('machineDetails', 'externalIP'),
           userProfile.get('machineDetails', 'listeningPort'),
           userProfile.get('machineDetails', 'nodeid')
                                    ))
    if NEWBORN:
        print('Aether is newborn. This is the first run of Aether on this machine, '
              'or the profile was completely deleted beforehand.')

def quitApp(reactor):
    # The global app quit routine.
    # This is (probably) buggy...
    if reactor.threadpool is not None:
        reactor.threadpool.stop()
    reactor.stop()
    sys.exit()

def raiseAndFocusApp():
    # On OS X, this raises the into the focus and to the frontmost level.
    raiseWindowCmd = \
    '''osascript<<END
    tell application "Aether"
    activate
    end tell
    END'''
    import signal, time
    p = subprocess.Popen(raiseWindowCmd, shell=True)
    time.sleep(0.01)
    d = os.kill(p.pid, signal.SIGKILL) # so as to stop errors emanating from this.

    # HA. This is funny. For the dear reader who's appalled by what's going on here: There is no way
    # to get raise behaviour on Mac otherwise. Because when I try to raise through normal ways, it tries to
    # raise PyInstaller's bootloader, which is hidden and frozen. If you try to not kill the subprocess,
    # Applescript will take ownership of the process and it will just wait until the end of time.
    # Every time you execute this you would be creating a new process which does absolutely nothing, yet
    # impossible to quit, as they're also frozen because of PyInstaller.


