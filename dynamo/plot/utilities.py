import numpy as np
from scipy.stats import norm
from sklearn.neighbors import NearestNeighbors

# plotting utility functions from https://github.com/velocyto-team/velocyto-notebooks/blob/master/python/DentateGyrus.ipynb

def despline():
    import matplotlib.pyplot as plt

    ax1 = plt.gca()
    # Hide the right and top spines
    ax1.spines['right'].set_visible(False)
    ax1.spines['top'].set_visible(False)
    # Only show ticks on the left and bottom spines
    ax1.yaxis.set_ticks_position('left')
    ax1.xaxis.set_ticks_position('bottom')

def minimal_xticks(start, end):
    import matplotlib.pyplot as plt

    end_ = np.around(end, -int(np.log10(end))+1)
    xlims = np.linspace(start, end_, 5)
    xlims_tx = [""]*len(xlims)
    xlims_tx[0], xlims_tx[-1] = f"{xlims[0]:.0f}", f"{xlims[-1]:.02f}"
    plt.xticks(xlims, xlims_tx)


def minimal_yticks(start, end):
    import matplotlib.pyplot as plt

    end_ = np.around(end, -int(np.log10(end))+1)
    ylims = np.linspace(start, end_, 5)
    ylims_tx = [""]*len(ylims)
    ylims_tx[0], ylims_tx[-1] = f"{ylims[0]:.0f}", f"{ylims[-1]:.02f}"
    plt.yticks(ylims, ylims_tx)


def diffusionMatrix(V_mat):
    """Function to calculate cell-specific diffusion matrix for based on velocity vectors of neighbors.

    Parameters
    ----------
        V_mat: `np.ndarray`
            velocity vectors of neighbors

    Returns
    -------
        Return the cell-specific diffusion matrix
    """

    D = np.zeros((V_mat.shape[0], 2, 2))  # this one works for two dimension -- generalize it to high dimensions
    D[:, 0, 0] = np.mean((V_mat[:, :, 0] - np.mean(V_mat[:, :, 0], axis=1)[:, None]) ** 2, axis=1)
    D[:, 1, 1] = np.mean((V_mat[:, :, 1] - np.mean(V_mat[:, :, 1], axis=1)[:, None]) ** 2, axis=1)
    D[:, 0, 1] = np.mean((V_mat[:, :, 0] - np.mean(V_mat[:, :, 0], axis=1)[:, None]) * (
                V_mat[:, :, 0] - np.mean(V_mat[:, :, 0], axis=1)[:, None]), axis=1)
    D[:, 1, 0] = D[:, 0, 1]

    return D / 2


def velocity_on_grid(X_emb, V_emb, xy_grid_nums, density=None, smooth=None, n_neighbors=None, min_mass=None, autoscale=False,
                             adjust_for_stream=True, V_threshold=None):
    """Function to calculate the velocity vectors on a grid for grid vector field  quiver plot and streamplot, adapted from scVelo
    """

    n_obs, n_dim = X_emb.shape
    density = 1 if density is None else density
    smooth = .5 if smooth is None else smooth

    grs = []
    for dim_i in range(n_dim):
        m, M = np.min(X_emb[:, dim_i]), np.max(X_emb[:, dim_i])
        m = m - .01 * np.abs(M - m)
        M = M + .01 * np.abs(M - m)
        gr = np.linspace(m, M, xy_grid_nums[dim_i] * density)
        grs.append(gr)

    meshes_tuple = np.meshgrid(*grs)
    X_grid = np.vstack([i.flat for i in meshes_tuple]).T

    # estimate grid velocities
    if n_neighbors is None: n_neighbors = int(n_obs / 50)
    nn = NearestNeighbors(n_neighbors=n_neighbors, n_jobs=-1)
    nn.fit(X_emb)
    dists, neighs = nn.kneighbors(X_grid)

    scale = np.mean([(g[1] - g[0]) for g in grs]) * smooth
    weight = norm.pdf(x=dists, scale=scale)
    p_mass = weight.sum(1)

    V_grid = (V_emb[neighs] * weight[:, :, None]).sum(1) / np.maximum(1, p_mass)[:, None]

    # calculate diffusion matrix D
    D = diffusionMatrix(V_emb[neighs])

    if adjust_for_stream:
        X_grid = np.stack([np.unique(X_grid[:, 0]), np.unique(X_grid[:, 1])])
        ns = int(np.sqrt(len(V_grid[:, 0])))
        V_grid = V_grid.T.reshape(2, ns, ns)

        mass = np.sqrt((V_grid ** 2).sum(0))
        if V_threshold is not None:
            V_grid[0][mass.reshape(V_grid[0].shape) < V_threshold] = np.nan
    else:
        if min_mass is None: min_mass = np.clip(np.percentile(p_mass, 99) / 100, 1e-2, 1)
        X_grid, V_grid = X_grid[p_mass > min_mass], V_grid[p_mass > min_mass]

        if autoscale: V_grid /= 3 * quiver_autoscaler(X_grid, V_grid)

    return X_grid, V_grid, D


def quiver_autoscaler(X_emb, V_emb):
    """Function to automatically calculate the value for the scale parameter of quiver plot, adapted from scVelo

    Parameters
    ----------
        X_emb: `np.ndarray`
            X, Y-axis coordinates
        V_emb:  `np.ndarray`
            Velocity (U, V) values on the X, Y-axis

    Returns
    -------
        The scale for quiver plot
    """

    import matplotlib.pyplot as plt
    scale_factor = np.ptp(X_emb, 0).mean()
    X_emb = X_emb - X_emb.min(0)

    if len(V_emb.shape) == 3:
        Q = plt.quiver(X_emb[0] / scale_factor, X_emb[1] / scale_factor,
                   V_emb[0], V_emb[1], angles='xy', scale_units='xy', scale=None)
    else:
        Q = plt.quiver(X_emb[:, 0] / scale_factor, X_emb[:, 1] / scale_factor,
                      V_emb[:, 0], V_emb[:, 1], angles='xy', scale_units='xy', scale=None)

    Q._init()
    plt.clf()

    return Q.scale / scale_factor
