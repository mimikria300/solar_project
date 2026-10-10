#one export click = one ExportJob, built once by the dispatcher from the validated forms
from dataclasses import dataclass, replace
import datetime as dt


@dataclass(frozen=True) #made to make instances immutable; may be useful for safety
class ExportJob:
    export_format: str
    variables: object #Variable queryset from VariableSelectForm
    ts_start: dt.datetime
    ts_end: dt.datetime
    aggregate: bool
    validate: bool 
    split_by_day: bool = False #clean_cdf only: one file per UTC day
    split_by_resolution: bool = False #clean_cdf only: one CDF per var group instead of all groups of a dataset in one

    @property #re-computed on read
    def dt_str(self):
        '''Requested range for filenames; aggregated exports swap in the real bin range.'''
        return self.ts_start.strftime('%Y%m%d%H%M') + '_' + self.ts_end.strftime('%Y%m%d%H%M')

    @property #re-computed on read
    def mode_tag(self):
        return f"{'agg' if self.aggregate else 'full'}_{'val' if self.validate else 'raw'}"

    def for_range(self, ts_start, ts_end):
        '''Same job, other time range (frozen, so a new copy).'''
        return replace(self, ts_start=ts_start, ts_end=ts_end)

    def day_jobs(self):
        '''One job per UTC day of the requested range; first and last day cut to the request.'''
        day = self.ts_start.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        while day < self.ts_end:
            next_day = day + dt.timedelta(days=1)
            yield self.for_range(max(day, self.ts_start), min(next_day, self.ts_end))
            day = next_day

    def var_groups(self):
        '''One var per file group (dataset + depend_0).'''
        return list(self.variables.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'))

    def group_vars(self, item):
        '''All requested vars of the group that item stands for.'''
        return self.variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
