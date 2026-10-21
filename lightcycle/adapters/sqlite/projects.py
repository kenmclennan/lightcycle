from lightcycle.domain.work import format_facets, unformat_facets
from lightcycle.ports.store import ProjectEntry


class ProjectsAggregate:
    def add_project(
        self, identity, *, shortcode=None, local_path=None, remote=None, facets=None
    ):
        row = self._conn.execute(
            "SELECT shortcode, local_path, remote, facets FROM projects WHERE identity = ?",
            (identity,),
        ).fetchone()
        stored_facets = format_facets(facets) if facets is not None else None
        if row is None:
            self._conn.execute(
                "INSERT INTO projects (identity, shortcode, local_path, remote, facets) "
                "VALUES (?, ?, ?, ?, ?)",
                (identity, shortcode, local_path, remote, stored_facets or ""),
            )
        else:
            merged = (
                shortcode if shortcode is not None else row[0],
                local_path if local_path is not None else row[1],
                remote if remote is not None else row[2],
                stored_facets if stored_facets is not None else row[3],
            )
            self._conn.execute(
                "UPDATE projects SET shortcode = ?, local_path = ?, remote = ?, facets = ? "
                "WHERE identity = ?",
                (*merged, identity),
            )
        self._commit()

    @staticmethod
    def _project_entry(row):
        return ProjectEntry(*row[:4], unformat_facets(row[4]))

    def get_project(self, identity):
        row = self._conn.execute(
            "SELECT identity, shortcode, local_path, remote, facets FROM projects "
            "WHERE identity = ?",
            (identity,),
        ).fetchone()
        return self._project_entry(row) if row else None

    def list_projects(self):
        rows = self._conn.execute(
            "SELECT identity, shortcode, local_path, remote, facets FROM projects "
            "ORDER BY identity"
        ).fetchall()
        return [self._project_entry(row) for row in rows]

    def remove_project(self, identity):
        cur = self._conn.execute("DELETE FROM projects WHERE identity = ?", (identity,))
        self._commit()
        if cur.rowcount == 0:
            raise KeyError("project not registered: %s" % identity)
