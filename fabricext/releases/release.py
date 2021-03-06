'''
Fabric Deploy Strategy
'''

import os.path
from datetime import date, datetime

from fabric.api import *  # noqa
from fabric.colors import green
from fabric.utils import error, warn
from fabric.contrib.files import exists

from .transaction import Transaction
from .util import execute_pseudo_task


class Release(Transaction):
    '''Wrap deployment code in a release deploy strategy, which provided
    rollback on error and release rollback.

    The release strategy mimics Capistranos deploy strategy. It builds out a
    directory structure that includes the current version deployed, previous
    releases named by date, and shared resources separate from deployed code::

        base_path/
          - @current (-> 2013-01-01.123456)
          - releases/
            - 2013-01-05.12345/
            - 2013-01-01.12356/
          - shared/
            - uploads/
            - files/
            - logs/

    The :py:class:`.Release` module would be used similar to the
    :py:class:`fabricext.deploy.Transaction`, as a context manager::

        with release('/tmp/path/release') as r:
            print env.base_dir
            print r.releases()

    The context manager handles creation of the above path structure before
    performing a release, and on a thrown exception, performs a rollback on
    commands executed. The context manager also sets `env.base_dir` to the
    current release path.

    :param base_path: base path to release
    :param shared: override shared paths for the release
    '''

    shared = ['log']

    def __init__(self, base_path, shared=None):
        # Sets up internally used paths
        self.base_path = base_path
        if shared is not None:
            self.shared = shared
        self.current_rel = None
        self.previous_rel = None
        self.release_path = os.path.join(base_path, 'releases')
        self.current_path = os.path.join(base_path, 'current')
        self.shared_path = os.path.join(base_path, 'shared')
        super(Release, self).__init__()

    def __enter__(self):
        execute_pseudo_task(fn=self.setup)
        super(Release, self).__enter__()
        return self

    def __exit__(self, type, value, tb):
        if tb is not None:
            error('Release failed.', func=warn, exception=value)
        else:
            puts(green('Release successful.'))
            execute_pseudo_task(fn=self.symlink)
            execute_pseudo_task(fn=self.cleanup)
        super(Release, self).__exit__(type, value, tb)

    def setup(self):
        '''Set up release paths and shared content.

        Create release and shared paths if missing. Then, create a new path,
        generated based on the time, for the new release. This will set the
        env variable `env.base_dir` to the fresh path.
        '''
        puts(green('Setting up release paths.'))
        if not exists(self.base_path, verbose=True):
            error('Missing base path.')
        with settings(warn_only=True):
            for path in [self.release_path, self.shared_path]:
                if not exists(path):
                    run('mkdir -p {0}'.format(path))
        self.create_release()

    def create_release(self):
        '''Make new release path.

        This generates a name for a new release and creates the release in the
        releases path. This also sets up the path for rollback, removing the
        created paths. Finally, it links the shared paths into the release.
        '''
        puts(green('Creating new release path'))
        # Make dir for release
        env.base_dir = self.current_release_path()
        run('mkdir -p {0}'.format(env.base_dir))
        self.on_rollback(lambda: execute_pseudo_task(fn=self.revert_release))
        for shared_path in self.shared:
            self.link_shared(shared_path, create=True)

    def revert_release(self):
        '''Revert partially deployed release'''
        run('rm -rf \'{0}\''.format(env.base_dir))

    def current_release(self):
        '''Return or generate a new release name'''
        if self.current_rel is None:
            self.current_rel = self._gen_rel()
        return self.current_rel

    def current_release_path(self):
        '''Path for current release'''
        return os.path.join(self.release_path, self.current_release())

    def link_shared(self, name, create=False):
        '''Link a path in shared to the current release

        :param name: path in shared to link
        :param create: create shared path if not exists, default=False
        '''
        rel = os.path.join(self.current_release_path(), name)
        shared = os.path.join(self.shared_path, name)
        if not exists(shared):
            if create:
                run('mkdir {0}'.format(shared))
            else:
                error('Shared path {name} does not exists'.format(
                    name=name
                ))
        if not exists(rel):
            run('ln -s {shared} {rel}'.format(
                shared=shared,
                rel=rel
            ))

    def cleanup(self):
        '''Clean up old releases from the release path'''
        puts(green('Cleaning up releases.'))
        rels = self.releases()
        # TODO make number of release a config option?
        # Reverse list, truncate, and then run delete operation on remainder
        if len(rels) > 5:
            rels.reverse()
            del rels[:5]
            map(
                lambda d: run('rm -rf \'{0}\''.format(d)),
                [os.path.join(self.release_path, d) for d in rels]
            )

    def symlink(self):
        '''Symlink `current_path` to `current_rel`'''
        if exists(self.current_path):
            run('rm -rf {0}'.format(self.current_path))
        run('ln -nfs {0} {1}'.format(
            self.current_release_path(),
            self.current_path
        ))

    def rollback_release(self):
        '''Rollback to previous release.

        This method should be called on an instance of the :py:class:`.Release`,
        class, not as a context manager -- this would create a new release and
        wrap the logic with rollbacks.
        '''
        rels = self.releases()
        if len(rels) < 2:
            warn('No previous release found')
            return False
        old_rel = rels[-1]
        self.current_rel = rels[-2]
        puts(green('Rolling back release: {0} -> {1}.'.format(
            old_rel,
            self.current_rel
        )))
        self.symlink()
        run('rm -rf \'{0}\''.format(
            os.path.join(self.release_path, old_rel)
        ))

    def releases(self):
        '''Fetch a list of releases'''
        with hide('stdout'):
            rels = sorted(run('cd {0} && find * -maxdepth 0 -type d'.format(
                self.release_path
            )).split())
        return rels

    def _gen_rel(self):
        '''Generate release name from time'''
        curr_time = datetime.now()
        seconds = (
            curr_time.second +
            (curr_time.minute * 60) +
            (curr_time.hour * 3600)
        )
        return "{0}.{1}".format(
            date.today().isoformat(),
            seconds
        )


# For readability
def release(*args, **kwargs):
    return Release(*args, **kwargs)
