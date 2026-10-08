#one export click = one ExportJob, built once by the dispatcher from the validated forms
from dataclasses import dataclass
import datetime as dt


@dataclass(frozen=True)
class ExportJob:
    '''What the user asked for. Frozen: nothing down the pipeline can change it.'''
    export_format: str
    variables: object #Variable queryset from VariableSelectForm
    ts_start: dt.datetime
    ts_end: dt.datetime
    aggregate: bool
    validate: bool #from ExportForm (VariableSelectForm has its own "validate" too, not this one)

    @property
    def dt_str(self):
        '''Requested range for filenames; aggregated exports swap in the real bin range.'''
        return self.ts_start.strftime('%Y%m%d%H%M') + '_' + self.ts_end.strftime('%Y%m%d%H%M')

    @property
    def mode_tag(self):
        return f"{'agg' if self.aggregate else 'full'}_{'val' if self.validate else 'raw'}"

    def var_groups(self):
        '''One var per file group (dataset + depend_0).'''
        return list(self.variables.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'))

    def group_vars(self, item):
        '''All requested vars of the group that item stands for.'''
        return self.variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
