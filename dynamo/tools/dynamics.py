import warnings
import numpy as np
from .connectivity import smoother
from .velocity import velocity, estimation
from .utils import get_mapper, get_valid_inds, get_data_for_velocity_estimation, get_U_S_for_velocity_estimation
from .utils import set_velocity, set_param_deterministic, set_param_moment
from .utils import moment_model

# incorporate the model selection code soon
def dynamics(adata, tkey=None, filter_gene_mode='final', mode='deterministic', use_smoothed=True, group=None, protein_names=None,
             experiment_type=None, assumption_mRNA=None, assumption_protein='ss', NTR_vel=True, concat_data=False,
             log_unnormalized=True, one_shot_method='combined'):
    """Inclusive model of expression dynamics considers splicing, metabolic labeling and protein translation. It supports
    learning high-dimensional velocity vector samples for droplet based (10x, inDrop, drop-seq, etc), scSLAM-seq, NASC-seq
    sci-fate, scNT-seq or cite-seq datasets.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            AnnData object.
        tkey: `str` or None (default: None)
            The column key for the time label of cells in .obs. Used for either "steady_state" or non-"steady_state" mode or `moment`
            mode  with labeled data.
        filter_gene_mode: `str` (default: `final`)
            The string for indicating which mode (one of, {'final', 'basic', 'no'}) of gene filter will be used.
        mode: `str` (default: `deterministic`)
            string indicates which estimation mode will be used. Currently "deterministic" and "moment" methods are supported.
            A "model_selection" mode will be supported soon in which alpha, beta and gamma will be modeled as a function of time.
            Note that deterministic model only considers the mean of RNA species (based on the deterministic ordinary different
            equations) while moment method considers both first moment and second moment (uncentered variance) of RNA species (
            based on the stochastic master equations). Currently moment mode is supported for either the conventional scRNA-seq
            dataset or the kinetic experiments. However, one-shot, degradation and other innovative ways of labeling experiments
            will also be supported shortly.
        use_smoothed: `bool` (default: `True`)
            Whether to use the smoothed data when calculating velocity for each gene.
        group: `str` or None (default: `None`)
            The column key/name that identifies the grouping information (for example, clusters that correspond to different cell types)
            of cells. This will be used to estimate group-specific (i.e cell-type specific) kinetic parameters.
        protein_names: `List`
            A list of gene names corresponds to the rows of the measured proteins in the `X_protein` of the `obsm` attribute.
            The names have to be included in the adata.var.index.
        experiment_type: `str`
            single cell RNA-seq experiment type. Available options are:
            (1) 'conventional': conventional single-cell RNA-seq experiment;
            (1) 'deg': degradation experiment;
            (2) 'kin': synthesis/kinetics experiment;
            (3) 'one-shot': one-shot kinetic experiment.
        assumption_mRNA: `str`
            Parameter estimation assumption for mRNA. Available options are:
            (1) 'ss': pseudo steady state;
            (2) None: degradation and kinetic data with no assumption.
            If no labelling data exists, assumption_mRNA will automatically set to be 'ss'. For one-shot experiment, assumption_mRNA
            is set to be None. However we will use steady state assumption to estimate parameters alpha and gamma either by a deterministic
            linear regression or the first order decay approach in line of the sci-fate paper.
        assumption_protein: `str`
            Parameter estimation assumption for protein. Available options are:
            (1) 'ss': pseudo steady state;
        NTR_vel: `bool` (default: `True`)
            Whether to use NTR (new/total ratio) velocity for labeling datasets.
        concat_data: `bool` (default: `False`)
            Whether to concatenate data before estimation. If your data is a list of matrices for each time point, this need to be set as True.
        log_unnormalized: `bool` (default: `True`)
            Whether to log transform the unnormalized data.

    Returns
    -------
        adata: :class:`~anndata.AnnData`
            A updated AnnData object with estimated kinetic parameters and inferred velocity included.
    """

    if 'use_for_dynamo' not in adata.var.columns and 'pass_basic_filter' not in adata.var.columns:
        filter_gene_mode = 'no'

    valid_ind = get_valid_inds(adata, filter_gene_mode)

    if mode == 'moment' or (use_smoothed and len([i for i in adata.layers.keys() if i.startswith('M_')]) < 2):
        smoother(adata)

    valid_adata = adata[:, valid_ind].copy()
    if group is not None and group in adata.obs[group]:
        _group = adata.obs[group].unique()
    else:
        _group = ["_all_cells"]

    for cur_grp in _group:
        if cur_grp == '_all_cells':
            kin_param_pre = ''
            cur_cells_bools = np.ones(valid_adata.shape[0], dtype=bool)
            subset_adata = valid_adata[cur_cells_bools]
        else:
            kin_param_pre = group + '_' + cur_grp + '_'
            cur_cells_bools = (valid_adata.obs[group] == cur_grp).values
            subset_adata = valid_adata[cur_cells_bools]

        U, Ul, S, Sl, P, US, S2, t, normalized, has_splicing, has_labeling, has_protein, ind_for_proteins, assumption_mRNA, exp_type = \
            get_data_for_velocity_estimation(subset_adata, mode, use_smoothed, tkey, protein_names, experiment_type,
                                             log_unnormalized, NTR_vel)

        if exp_type is not None:
            if experiment_type != exp_type:
                warnings.warn('dynamo detects the experiment type of your data as {}, but your input experiment_type '
                              'is {}'.format(exp_type, experiment_type))

            experiment_type = exp_type
            assumption_mRNA = 'ss' if exp_type == 'conventional' else None
            NTR_vel = False

        if mode == 'moment' and experiment_type not in ['conventional', 'kin']:
            """
            # temporially convert to deterministic mode as moment mode for one-shot, 
            degradation and other types of labeling experiment is ongoing."""

            mode = 'deterministic'

        if mode is 'deterministic' or (experiment_type is not 'kin' and mode is 'moment'):
            est = estimation(U=U, Ul=Ul, S=S, Sl=Sl, P=P, US=US, S2=S2,
                             t=t, ind_for_proteins=ind_for_proteins,
                             experiment_type=experiment_type,
                             assumption_mRNA=assumption_mRNA,
                             assumption_protein=assumption_protein,
                             concat_data=concat_data)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")

                if experiment_type in ['one-shot', 'one_shot']:
                    est.fit(one_shot_method=one_shot_method)
                else:
                    est.fit()

            alpha, beta, gamma, eta, delta = est.parameters.values()

            U, S = get_U_S_for_velocity_estimation(subset_adata, use_smoothed, has_splicing, has_labeling, log_unnormalized, NTR_vel)
            vel = velocity(estimation=est)
            vel_U = vel.vel_u(U)
            vel_S = vel.vel_s(U, S)
            vel_P = vel.vel_p(S, P)

            adata = set_velocity(adata, vel_U, vel_S, vel_P, _group, cur_grp, cur_cells_bools, valid_ind, ind_for_proteins)

            adata = set_param_deterministic(adata, est, alpha, beta, gamma, eta, delta, experiment_type,_group, cur_grp,
                                            kin_param_pre, valid_ind, ind_for_proteins)

        elif mode is 'moment':
            adata, Est, t_ind = moment_model(adata, subset_adata, _group, cur_grp, log_unnormalized, tkey)
            t_ind += 1

            params, costs = Est.fit()
            a, b, alpha_a, alpha_i, beta, gamma = params[:, 0], params[:, 1], params[:, 2], params[:, 3], params[: ,4], params[:, 5]
            def fbar(x_a, x_i, a, b):
                return b / (a + b) * x_a + a / (a + b) * x_i

            alpha = fbar(alpha_a, alpha_i, a, b)[:, None]

            params = {'alpha': alpha, 'beta': beta, 'gamma': gamma, 't': t}
            vel = velocity(**params)

            U, S = get_U_S_for_velocity_estimation(subset_adata, use_smoothed, has_splicing, has_labeling, log_unnormalized, NTR_vel)
            vel_U = vel.vel_u(U)
            vel_S = vel.vel_s(U, S)
            vel_P = vel.vel_p(S, P)

            adata = set_velocity(adata, vel_U, vel_S, vel_P, _group, cur_grp, cur_cells_bools, valid_ind, ind_for_proteins)

            adata = set_param_moment(adata, a, b, alpha_a, alpha_i, beta, gamma, kin_param_pre, _group, cur_grp, valid_ind)
            # add protein related parameters in the moment model below:
        elif mode is 'model_selection':
            warnings.warn('Not implemented yet.')

    if group is not None and group in adata.obs[group]:
        uns_key = group + "_dynamics"
    else:
        uns_key = "dynamics"

    adata.uns[uns_key] = {'t': t, "group": group, 'asspt_mRNA': assumption_mRNA, 'experiment_type': experiment_type, "normalized": normalized, "mode": mode, "has_splicing": has_splicing,
                             "has_labeling": has_labeling, "has_protein": has_protein, "use_smoothed": use_smoothed, "NTR_vel": NTR_vel, "log_unnormalized": log_unnormalized}
    return adata
