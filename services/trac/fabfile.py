import os

from fabric.api import abort, env, run, settings, put

from braid import postgres, cron, archive, utils
from braid.twisted import service
from braid.utils import confirm

from braid import config
from braid.tasks import addTasks
__all__ = ['config']


class Trac(service.Service):

    python = "python"

    def task_install(self):
        """
        Install trac.
        """
        self.bootstrap()

        with settings(user=self.serviceUser):

            self.update()

            run('/bin/mkdir -p ~/attachments')
            run('/bin/ln -nsf ~/attachments {}/trac-env/files/attachments'.format(
                self.configDir))

            run('/bin/ln -nsf {} {}/trac-env/log'.format(self.logDir, self.configDir))

            run('/bin/ln -nsf {}/start {}/start'.format(self.configDir, self.binDir))

            cron.install(self.serviceUser, '{}/crontab'.format(self.configDir))

        # FIXME: Make these idempotent.
        postgres.createUser('trac')
        postgres.createDb('trac', 'trac')


    def update(self):
        """
        Remove the current trac installation and reinstalls it.
        """
        with settings(user=self.serviceUser):
            self.venv.create()

            run('mkdir -p ' + self.configDir)
            put(os.path.dirname(__file__) + '/*', self.configDir,
                mirror_local_mode=True)

            self.venv.install_twisted()
            self.venv.install(" ".join("""
                psycopg2==2.6.2
                pygments==1.6
                spambayes==1.1b2
                trac==1.2
                trac-github==2.2
                requests_oauthlib==0.6.1
                svn+https://svn.edgewall.org/repos/trac/plugins/1.2/spam-filter@15310
                git+https://github.com/twisted-infra/twisted-trac-plugins.git
            """.split()))


    def task_update(self):
        """
        Stop, remove the current Trac installation, reinstalls it and start.
        """
        try:
            self.task_stop()
        except:
            pass
        self.update()
        self.task_start()


    def task_upgrade(self):
        """
        Remove the existing installation, re-install it and run a Trac
        upgrade.
        """
        with settings(user=self.serviceUser):
            self.update()
            run("~/virtualenv/bin/trac-admin {}/trac-env upgrade".format(self.configDir))
            run("~/virtualenv/bin/trac-admin {}/trac-env wiki upgrade".format(self.configDir))

        self.task_restart()

    def task_getGithubMirror(self, twistedName='twisted-staging'):
        """
        Get a GitHub mirror.
        """
        with settings(user=self.serviceUser):
            run("git clone --mirror git://github.com/twisted/%s.git ~/twisted.git" % (twistedName,),
                warn_only=True)
            run("git --git-dir=/srv/trac/twisted.git remote update --prune")


    def task_dump(self, localfile, withAttachments=True):
        """
        Create a tarball containing all information not currently stored in
        version control and download it to the given C{localfile}.
        """
        with settings(user=self.serviceUser):
            with utils.tempfile() as temp:
                postgres.dumpToPath('trac', temp)

                files = {
                    'db.dump': temp,
                }

                if withAttachments is True:
                    files['attachments'] = 'attachments'

                archive.dump(files, localfile)


    def task_restore(self, localfile, restoreDb=True, withAttachments=True):
        """
        Restore all information not stored in version control from a tarball
        on the invoking users machine.
        """
        restoreDb = str(restoreDb).lower() in ('true', '1', 'yes', 'ok', 'y')

        if restoreDb:
            msg = (
                'All existing files present in the backup will be overwritten and\n'
                'the database dropped and recreated.'
            )
        else:
            msg = (
                'All existing files present in the backup will be overwritten\n'
                '(the database will not be touched).'
            )

        print ''
        if confirm(msg):
            # TODO: Ask for confirmation here
            if restoreDb:
                postgres.dropDb('trac')
                postgres.createDb('trac', 'trac')

            with settings(user=self.serviceUser):
                with utils.tempfile() as temp:
                    files = {
                        'db.dump': temp,
                    }

                    if withAttachments is True:
                        files['attachments'] = 'attachments'

                    archive.restore(files, localfile)
                    if restoreDb:
                        postgres.restoreFromPath('trac', temp)


    def task_installTestData(self):
        """
        Create an empty trac database for testing.
        """
        if env.get('environment') == 'production':
           abort("Don't use installTestData in production.")

        if postgres.tableExists('trac', 'system'):
           abort("Existing Trac tables found.")

        with settings(user=self.serviceUser):
            # Run trac initenv to create the postgresql database tables, but use
            # a throwaway trac-env directory because that comes from
            # https://github.com/twisted-infra/trac-config/tree/master/trac-env
            try:
                run('~/virtualenv/bin/trac-admin '
                    '/tmp/trac-init initenv TempTrac postgres://@/trac git ""')
            finally:
                run("rm -rf /tmp/trac-init")

            # Run an upgrade to add plugin specific database tables and columns.
            run('~/virtualenv/bin/trac-admin config/trac-env upgrade --no-backup')



addTasks(globals(), Trac('trac').getTasks())
