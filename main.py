# Future imports
from __future__ import print_function

# Kill this instance if another copy is running.

from tendo import singleton
me = singleton.SingleInstance()  # Will sys.exit(-1) if other instance is running

# Aether modules
import globals
from globals import FROZEN, PROFILE_DIR, PLATFORM, BASEDIR, AETHER_VERSION
from GUI.guiElements import *
from ORM import Hermes
from urllib import urlopen
import re

app = Aether()

#Python imports
import os

if FROZEN:
    del sys.modules['twisted.internet.reactor']
import qt5reactor
qt5reactor.install()

from twisted.internet import reactor
from InputOutput.Charon import Charon
from twisted.web.client import getPage
from twisted.internet import threads


if globals.userProfile.get('debugDetails', 'debugLogging'):
    from twisted.python import log
    from twisted.python.logfile import DailyLogFile
    log.startLogging(DailyLogFile.fromFullPath(PROFILE_DIR+'/Logs/interface.log'))
    globals.logSystemDetails()
else:
    def print(*a, **kwargs):
        pass

baseurl = os.getcwd()+'/'
if len(sys.argv) > 1 and sys.argv[1] == '-openatlogin':
    globals.APP_STARTED_AT_SYSTEM_STARTUP = True

if PLATFORM == 'OSX':
    import  objc
    import AppKit

    if FROZEN:
        class NSObjCApp(AppKit.AppKit.NSObject):
            @objc.signature('B@:#B')
            def applicationShouldHandleReopen_hasVisibleWindows_(self, nsAppObject, flag):
                app.onClickOnDock()
                return True
    else:
        class NSObjCApp(AppKit.NSObject):
            @objc.signature('B@:#B')
            def applicationShouldHandleReopen_hasVisibleWindows_(self, nsAppObject, flag):
                app.onClickOnDock()
                return True

    cls = objc.lookUpClass('NSApplication')
    appInstance = cls.sharedApplication() # I'm doing some real crazy runtime shit there.
    ta = NSObjCApp.alloc().init()
    appInstance.setDelegate_(ta)

if PLATFORM == 'LNX':
    app.setStyle("Fusion")
    # This is a fix to 'CRITICAL: GTK_IS_WIDGET (widget)' failed' bug on Debian / Ubuntu.
    # Visually it doesn't change anything, it's just an explicit declaration to help Unity.

def main():

    global reactor

    from twisted.internet import reactor

    print('Spawning the networking daemon...')
    # Spawn the networking daemon.
    from InputOutput import interprocessChildProt
    from ampoule_aether import pool
    from  InputOutput import interprocessParentProt
    from ampoule_aether import main as ampouleMain

    if FROZEN:
        procStarter = ampouleMain.ProcessStarter()
    else:
        procStarter = ampouleMain.ProcessStarter(bootstrap=interprocessChildProt.childBootstrap)


    global pp
    pp = pool.ProcessPool(interprocessChildProt.NetworkingProcessProtocol,
                          ampParent=interprocessParentProt.MainProcessProtocol,
                          starter=procStarter,
                          recycleAfter=0,
                          min=1, max=1)

    pp.start()
    pp.ampParent.processPool = pp # Self referential much?
    # Networking daemon spawnage ends here.
    print('Networking daemon spawned.')


    hermes = Hermes.Hermes(pp)

    charon = Charon(hermes)
    view = AetherMainWindow(charon, reactor, baseurl, app)
    if PLATFORM == 'OSX' or PLATFORM == 'WIN':
        trayIcon = SystemTrayIcon(BASEDIR, app, view)
    # trayIcon.protInstance = protInstance
    # protInstance.trayIcon = trayIcon
    ef = ModifierEventFilter()
    app.view = view
    ef.view = view
    view.pp = pp
    if PLATFORM == 'OSX' or PLATFORM == 'WIN':
        app.trayIcon = trayIcon
        view.trayIcon = trayIcon
        ef.trayIcon = trayIcon
        charon.trayIcon = trayIcon
        trayIcon.webView = view
        trayIcon.show()
    app.installEventFilter(ef)


    # Attach the items to the parent protocol, so it can react on the events arriving from networking daemon.
    pp.ampParent.Hermes = hermes
    if PLATFORM == 'OSX' or PLATFORM == 'WIN':
        pp.ampParent.trayIcon = trayIcon
    pp.ampParent.JSContext = view.JSContext


    if globals.userProfile.get('debugDetails', 'enableWebkitInspector'):
        from PyQt5.QtWebKit import QWebSettings
        QWebSettings.globalSettings().setAttribute(QWebSettings.DeveloperExtrasEnabled, True)
        inspect = QWebInspector()
        inspect.resize(1450, 300)
        inspect.move(0,0)
        inspect.setPage(view.webView.page())
        view.setContextMenuPolicy(Qt.DefaultContextMenu)
        inspect.show()

    splash.finish(view)
    if globals.APP_STARTED_AT_SYSTEM_STARTUP:
        if PLATFORM == 'LNX':
            # Because there is no tray icon on Linux, app starts minimised ( (-) state).
            view.showMinimized()
        elif PLATFORM == 'OSX' or PLATFORM == 'WIN':
            pass # Do nothing, there is already a tray icon in place.
    else: # If not started at boot
        view.show()


    def checkForUpdates():

        # One catch, any result available out of this will only be visible after next boot of the app.
        d = getPage('http://www.getaether.net/updatecheck')

        def processReceivedVersion(reply):
            if int(reply[:3]) > AETHER_VERSION:
                globals.userProfile.set('machineDetails', 'updateAvailable', True)
                print('There is an update available, local version is %d and gathered version is %s.'
                      % (AETHER_VERSION, reply))
            else:
                globals.userProfile.set('machineDetails', 'updateAvailable', False)
                print('There is no update available')

        return d.addCallback(processReceivedVersion)

    if globals.userProfile.get('machineDetails', 'checkForUpdates'):
        d = checkForUpdates()
        d.addErrback(print,
                     'Checking for updates failed. Either the server is down, or the internet connection is not available.')

    def setPublicIPAddress():
        # For privacy reasons, this can be disabled by setting 'allowPublicIPLookup' to false at your user profile json.
        # The only use case for this is to show you your IP address in the settings, so you can give your IP address
        # and port to your friend to use you as the bootstrap node. If you can read this, you don't need that. Disable.
        data = str(urlopen('http://checkip.dyndns.com/').read())
        result = re.compile(r'Address: (\d+\.\d+\.\d+\.\d+)').search(data).group(1)
        globals.userProfile.set('machineDetails', 'externalIP', result)
        print('Public IP of this machine is %s' % result)
        return True



    if globals.userProfile.get('machineDetails', 'allowPublicIPLookup'):
        d2 = threads.deferToThread(setPublicIPAddress)
        # d2.addErrback(print, 'The public IP address could not be found. The internet connection is not available.')

    reactor.run()

if __name__ == "__main__":

    pixmap = QtGui.QPixmap(BASEDIR+'Assets/splash.png')
    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)

    print('profiledir:')
    print(PROFILE_DIR)

    if not globals.APP_STARTED_AT_SYSTEM_STARTUP:
        splash.show()
    main()

    if reactor.threadpool is not None:
        reactor.threadpool.stop()
        reactor.stop()
        sys.exit()
