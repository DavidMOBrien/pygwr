# -*- coding: utf-8 -*-
"""Sandwich covariance estimators


Created on Sun Nov 27 14:10:57 2011

Author: Josef Perktold
Author: Skipper Seabold for HCxxx in linear_model.RegressionResults
License: BSD-3

Notes
-----

for calculating it, we have two versions

version 1: use pinv
pinv(x) scale pinv(x)   used currently in linear_model, with scale is
1d (or diagonal matrix)
(x'x)^(-1) x' scale x (x'x)^(-1),  scale in general is (nobs, nobs) so
pretty large
general formulas for scale in cluster case are in
http://pubs.amstat.org/doi/abstract/10.1198/jbes.2010.07136 which also
has the second version

version 2:
(x'x)^(-1) S (x'x)^(-1)    with S = x' scale x,    S is (kvar,kvars),
(x'x)^(-1) is available as normalized_covparams.



S = sum (x*u) dot (x*u)' = sum x*u*u'*x'  where sum here can aggregate
over observations or groups. u is regression residual.

x is (nobs, k_var)
u is (nobs, 1)
x*u is (nobs, k_var)


For cluster robust standard errors, we first sum (x*w) over other groups
(including time) and then take the dot product (sum of outer products)

S = sum_g(x*u)' dot sum_g(x*u)
For HAC by clusters, we first sum over groups for each time period, and then
use HAC on the group sums of (x*w).
If we have several groups, we have to sum first over all relevant groups, and
then take the outer product sum. This can be done by summing using indicator
functions or matrices or with explicit loops. Alternatively we calculate
separate covariance matrices for each group, sum them and subtract the
duplicate counted intersection.

Not checked in details yet: degrees of freedom or small sample correction
factors, see (two) references (?)


This is the general case for MLE and GMM also

in MLE     hessian H, outerproduct of jacobian S,   cov_hjjh = HJJH,
which reduces to the above in the linear case, but can be used
generally, e.g. in discrete, and is misnomed in GenericLikelihoodModel

in GMM it's similar but I would have to look up the details, (it comes
out in sandwich form by default, it's in the sandbox), standard Newey
West or similar are on the covariance matrix of the moment conditions

quasi-MLE: MLE with mis-specified model where parameter estimates are
fine (consistent ?) but cov_params needs to be adjusted similar or
same as in sandwiches. (I didn't go through any details yet.)

TODO
----
* small sample correction factors, Done for cluster, not yet for HAC
* automatic lag-length selection for Newey-West HAC,
  -> added: nlag = floor[4(T/100)^(2/9)]  Reference: xtscc paper, Newey-West
     note this will not be optimal in the panel context, see Peterson
* HAC should maybe return the chosen nlags
* get consistent notation, varies by paper, S, scale, sigma?
* replace diag(hat_matrix) calculations in cov_hc2, cov_hc3


References
----------
John C. Driscoll and Aart C. Kraay, “Consistent Covariance Matrix Estimation
with Spatially Dependent Panel Data,” Review of Economics and Statistics 80,
no. 4 (1998): 549-560.

Daniel Hoechle, "Robust Standard Errors for Panel Regressions with
Cross-Sectional Dependence", The Stata Journal

Mitchell A. Petersen, “Estimating Standard Errors in Finance Panel Data
Sets: Comparing Approaches,” Review of Financial Studies 22, no. 1
(January 1, 2009): 435 -480.

A. Colin Cameron, Jonah B. Gelbach, and Douglas L. Miller, “Robust Inference
With Multiway Clustering,” Journal of Business and Economic Statistics 29
(April 2011): 238-249.


not used yet:
A.C. Cameron, J.B. Gelbach, and D.L. Miller, “Bootstrap-based improvements
for inference with clustered errors,” The Review of Economics and
Statistics 90, no. 3 (2008): 414–427.

"""

import numpy as np
from numpy.testing import assert_almost_equal

from gwstatsmodels.tools.grouputils import Group


def se_cov(cov):
    '''get standard deviation from covariance matrix

    just a shorthand function np.sqrt(np.diag(cov))

    Parameters
    ----------
    cov : array_like, square
        covariance matrix

    Returns
    -------
    std : ndarray
        standard deviation from diagonal of cov

    '''
    return np.sqrt(np.diag(cov))

#----------- from linear_model.RegressionResults
'''
    HC0_se
        White's (1980) heteroskedasticity robust standard errors.
        Defined as sqrt(diag(X.T X)^(-1)X.T diag(e_i^(2)) X(X.T X)^(-1)
        where e_i = resid[i]
        HC0_se is a property.  It is not evaluated until it is called.
        When it is called the RegressionResults instance will then have
        another attribute cov_HC0, which is the full heteroskedasticity
        consistent covariance matrix and also `het_scale`, which is in
        this case just resid**2.  HCCM matrices are only appropriate for OLS.
    HC1_se
        MacKinnon and White's (1985) alternative heteroskedasticity robust
        standard errors.
        Defined as sqrt(diag(n/(n-p)*HC_0)
        HC1_se is a property.  It is not evaluated until it is called.
        When it is called the RegressionResults instance will then have
        another attribute cov_HC1, which is the full HCCM and also `het_scale`,
        which is in this case n/(n-p)*resid**2.  HCCM matrices are only
        appropriate for OLS.
    HC2_se
        MacKinnon and White's (1985) alternative heteroskedasticity robust
        standard errors.
        Defined as (X.T X)^(-1)X.T diag(e_i^(2)/(1-h_ii)) X(X.T X)^(-1)
        where h_ii = x_i(X.T X)^(-1)x_i.T
        HC2_se is a property.  It is not evaluated until it is called.
        When it is called the RegressionResults instance will then have
        another attribute cov_HC2, which is the full HCCM and also `het_scale`,
        which is in this case is resid^(2)/(1-h_ii).  HCCM matrices are only
        appropriate for OLS.
    HC3_se
        MacKinnon and White's (1985) alternative heteroskedasticity robust
        standard errors.
        Defined as (X.T X)^(-1)X.T diag(e_i^(2)/(1-h_ii)^(2)) X(X.T X)^(-1)
        where h_ii = x_i(X.T X)^(-1)x_i.T
        HC3_se is a property.  It is not evaluated until it is called.
        When it is called the RegressionResults instance will then have
        another attribute cov_HC3, which is the full HCCM and also `het_scale`,
        which is in this case is resid^(2)/(1-h_ii)^(2).  HCCM matrices are
        only appropriate for OLS.

'''

def _HCCM(results, scale):
    '''
    sandwich with pinv(x) * diag(scale) * pinv(x).T

    where pinv(x) = (X'X)^(-1) X
    and scale is (nobs,)
    '''
    H = np.dot(results.model.pinv_wexog,
        scale[:,None]*results.model.pinv_wexog.T)
    return H

def cov_hc0(results):
    """
    See gwstatsmodels.RegressionResults
    """

    het_scale = results.resid**2 # or whitened residuals? only OLS?
    cov_hc0_ = _HCCM(results, het_scale)

    return cov_hc0_

def cov_hc1(results):
    """
    See gwstatsmodels.RegressionResults
    """

    het_scale = results.nobs/(results.df_resid)*(results.resid**2)
    cov_hc1_ = _HCCM(results, het_scale)
    return cov_hc1_

def cov_hc2(results):
    """
    See gwstatsmodels.RegressionResults
    """

    # probably could be optimized
    h = np.diag(np.dot(results.model.exog,
                          np.dot(results.normalized_cov_params,
                          results.model.exog.T)))
    het_scale = results.resid**2/(1-h)
    cov_hc2_ = _HCCM(results, het_scale)
    return cov_hc2_

def cov_hc3(results):
    """
    See gwstatsmodels.RegressionResults
    """

    # above probably could be optimized to only calc the diag
    h = np.diag(np.dot(results.model.exog,
                          np.dot(results.normalized_cov_params,
                          results.model.exog.T)))
    het_scale=(results.resid/(1-h))**2
    cov_hc3_ = _HCCM(results, het_scale)
    return cov_hc3_

#---------------------------------------


def _HCCM1(results, scale):
    '''
    sandwich with pinv(x) * scale * pinv(x).T

    where pinv(x) = (X'X)^(-1) X
    and scale is (nobs, nobs), or (nobs,) with diagonal matrix diag(scale)

    Parameters
    ----------
    results : result instance
       need to contain regression results, uses results.model.pinv_wexog
    scale : ndarray (nobs,) or (nobs, nobs)
       scale matrix, treated as diagonal matrix if scale is one-dimensional

    Returns
    -------
    H : ndarray (k_vars, k_vars)
        robust covariance matrix for the parameter estimates

    '''
    if scale.ndim == 1:
        H = np.dot(results.model.pinv_wexog,
                   scale[:,None]*results.model.pinv_wexog.T)
    else:
        H = np.dot(results.model.pinv_wexog,
                   np.dot(scale, results.model.pinv_wexog.T))
    return H

def _HCCM2(results, scale):
    '''
    sandwich with (X'X)^(-1) * scale * (X'X)^(-1)

    scale is (kvars, kvars)
    this uses results.normalized_cov_params for (X'X)^(-1)

    Parameters
    ----------
    results : result instance
       need to contain regression results, uses results.normalized_cov_params
    scale : ndarray (k_vars, k_vars)
       scale matrix

    Returns
    -------
    H : ndarray (k_vars, k_vars)
        robust covariance matrix for the parameter estimates

    '''
    if scale.ndim == 1:
        scale = scale[:,None]

    xxi = results.normalized_cov_params
    H = np.dot(np.dot(xxi, scale), xxi.T)
    return H

#TODO: other kernels, move ?
def weights_bartlett(nlags):
    '''Bartlett weights for HAC

    this will be moved to another module

    Parameters
    ----------
    nlags : int
       highest lag in the kernel window

    Returns
    -------
    kernel : ndarray, (nlags+1,)
        weights for Bartlett kernel

    '''

    #with lag zero
    return 1 - np.arange(nlags+1)/(nlags+1.)


def S_hac_simple(x, nlags=None, weights_func=weights_bartlett):
    '''inner covariance matrix for HAC (Newey, West) sandwich

    assumes we have a single time series with zero axis consecutive, equal
    spaced time periods


    Parameters
    ----------
    x : ndarray (nobs,) or (nobs, k_var)
        data, for HAC this is array of x_i * u_i
    nlags : int or None
        highest lag to include in kernel window. If None, then
        nlags = floor[4(T/100)^(2/9)] is used.
    weights_func : callable
        weights_func is called with nlags as argument to get the kernel
        weights. default are Bartlett weights

    Returns
    -------
    S : ndarray, (k_vars, k_vars)
        inner covariance matrix for sandwich

    Notes
    -----
    used by cov_hac_simple

    verified only for nlags=0, which is just White, through cov_hac_simple

    options might change when other kernels besides Bartlett are available.

    '''

    if x.ndim == 1:
        x = x[:,None]
    n_periods = x.shape[0]
    if nlags is None:
        nlags = np.floor[4 * (n_periods / 100.)**(2./9.)]

    weights = weights_func(nlags)

    S = weights[0] * np.dot(x.T, x)  #weights[0] just for completeness, is 1

    for lag in range(1, nlags+1):
        s = np.dot(x[lag:].T, x[:-lag])
        S += weights[lag] * (s + s.T)

    return S

def S_white_simple(x):
    '''inner covariance matrix for White heteroscedastistity sandwich


    Parameters
    ----------
    x : ndarray (nobs,) or (nobs, k_var)
        data, for HAC this is array of x_i * u_i

    Returns
    -------
    S : ndarray, (k_vars, k_vars)
        inner covariance matrix for sandwich

    Notes
    -----
    this is just dot(X.T, X)

    '''
    if x.ndim == 1:
        x = x[:,None]

    return np.dot(x.T, x)



def group_sums(x, group):
    '''sum x for each group, simple bincount version, again

    group : array, integer
        assumed to be consecutive integers

    no dtype checking because I want to raise in that case

    uses loop over columns of x

    #TODO: remove this, already copied to tools/grouputils
    '''

    return np.array([np.bincount(group, weights=x[:,col])
                            for col in range(x.shape[1])])


def S_hac_groupsum(x, time, nlags=None, weights_func=weights_bartlett):
    '''inner covariance matrix for HAC over group sums sandwich

    This assumes we have complete equal spaced time periods.
    The number of time periods per group need not be the same, but we need
    at least one observation for each time period

    For a single categorical group only, or a everything else but time
    dimension. This first aggregates x over groups for each time period, then
    applies HAC on the sum per period.

    Parameters
    ----------
    x : ndarray (nobs,) or (nobs, k_var)
        data, for HAC this is array of x_i * u_i
    time : ndarray, (nobs,)
        timeindes, assumed to be integers range(n_periods)
    nlags : int or None
        highest lag to include in kernel window. If None, then
        nlags = floor[4(T/100)^(2/9)] is used.
    weights_func : callable
        weights_func is called with nlags as argument to get the kernel
        weights. default are Bartlett weights

    Returns
    -------
    S : ndarray, (k_vars, k_vars)
        inner covariance matrix for sandwich


    not verified

    Reference
    ---------
    Daniel Hoechle, xtscc paper
    Driscoll and Kraay

    '''
    #needs groupsums

    x_group_sums = group_sums(x, time)

    return S_hac_simple(x_group_sums, nlags=nlags, weights_func=weights_func)


def S_crosssection(x, group):
    '''inner covariance matrix for White on group sums sandwich

    I guess for a single categorical group only,
    categorical group, can also be the product/intersection of groups

    This is used by cov_cluster and indirectly verified

    '''
    
    #needs groupsums

    x_group_sums = group_sums(x, group)

    return S_white_simple(x_group_sums)


def cov_crosssection_0(results, group):
    '''this one is still wrong, use cov_cluster instead'''

    #TODO: currently used version of groupsums requires 2d resid
    scale = S_crosssection(results.resid[:,None], group)
    scale = np.squeeze(scale)
    c = _HCCM1(results, scale)
    bse = np.sqrt(np.diag(c))
    return c, bse

def cov_cluster(results, group, use_correction=True):
    '''cluster robust covariance matrix

    Calculates sandwich covariance matrix for a single cluster, i.e. grouped
    variables.

    Parameters
    ----------
    results : result instance
       result of a regression, uses results.model.exog and results.resid
       TODO: this should use wexog instead
    use_correction : bool
       If true (default), then the small sample correction factor is used.

    Returns
    -------
    cov : ndarray, (k_vars, k_vars)
        cluster robust covariance matrix for parameter estimates
    bse : ndarray, (k_vars,)
        standard errors, this will be dropped

    Notes
    -----
    same result as Stata in UCLA example and same as Peterson

    '''
    #TODO: currently used version of groupsums requires 2d resid
    xu = results.model.exog * results.resid[:, None]
    scale = S_crosssection(xu, group)

    nobs, k_vars = results.model.exog.shape
    n_groups = len(np.unique(group)) #replace with stored group attributes if available

    cov_c = _HCCM2(results, scale)

    if use_correction:
        cov_c *= n_groups / (n_groups - 1.) * ((nobs-1.) / float(nobs - k_vars))

    bse_c = np.sqrt(np.diag(cov_c))
    return cov_c, bse_c

def cov_cluster_2groups(results, group, group2=None, use_correction=True):
    '''cluster robust covariance matrix for two groups/clusters

    Parameters
    ----------
    results : result instance
       result of a regression, uses results.model.exog and results.resid
       TODO: this should use wexog instead
    use_correction : bool
       If true (default), then the small sample correction factor is used.

    Returns
    -------
    cov_both : ndarray, (k_vars, k_vars)
        cluster robust covariance matrix for parameter estimates, for both
        clusters
    cov_0 : ndarray, (k_vars, k_vars)
        cluster robust covariance matrix for parameter estimates for first
        cluster
    cov_1 : ndarray, (k_vars, k_vars)
        cluster robust covariance matrix for parameter estimates for second
        cluster

    Notes
    -----

    verified against Peterson's table, (4 decimal print precision)
    '''

    if group2 is None:
        if group.ndim !=2 or group.shape[1] != 2:
            raise ValueError('if group2 is not given, then groups needs to be ' +
                             'an array with two columns')
        group0 = group[:, 0]
        group1 = group[:, 1]
    else:
        group0 = group
        group1 = group2
        group = (group0, group1)


    cov0 = cov_cluster(results, group0, use_correction=use_correction)[0]
    #[0] because we get still also returns bse
    cov1 = cov_cluster(results, group1, use_correction=use_correction)[0]

    group_intersection = Group(group)
    #cov of cluster formed by intersection of two groups
    cov01 = cov_cluster(results,
                        group_intersection.group_int,
                        use_correction=use_correction)[0]

    #robust cov matrix for union of groups
    cov_both = cov0 + cov1 - cov01

    #return all three (for now?)
    return cov_both, cov0, cov1


def cov_white_simple(results, use_correction=True):
    '''
    heteroscedasticity robust covariance matrix (White)

    Parameters
    ----------
    results : result instance
       result of a regression, uses results.model.exog and results.resid
       TODO: this should use wexog instead

    Returns
    -------
    cov : ndarray, (k_vars, k_vars)
        heteroscedasticity robust covariance matrix for parameter estimates
    bse : ndarray, (k_vars,)
        standard errors, this will be dropped

    Notes
    -----
    This produces the same result as cov_hc0, and does not include any small
    sample correction.

    verified (against LinearRegressionResults and Peterson)

    See Also
    --------
    cov_hc1, cov_hc2, cov_hc3 : heteroscedasticity robust covariance matrices
        with small sample corrections

    '''
    xu = results.model.exog * results.resid[:, None]
    sigma = S_white_simple(xu)

    cov_w = _HCCM2(results, sigma)  #add bread to sandwich

    if use_correction:
        nobs, k_vars = results.model.exog.shape
        cov_w *= nobs / float(nobs - k_vars)

    bse_w = np.sqrt(np.diag(cov_w))

    return cov_w, bse_w


def cov_hac_simple(results, nlags=None, weights_func=weights_bartlett,
                   use_correction=True):
    '''
    heteroscedasticity and autocorrelation robust covariance matrix (Newey-West)

    Assumes we have a single time series with zero axis consecutive, equal
    spaced time periods


    Parameters
    ----------
    results : result instance
       result of a regression, uses results.model.exog and results.resid
       TODO: this should use wexog instead
    nlags : int or None
        highest lag to include in kernel window. If None, then
        nlags = floor[4(T/100)^(2/9)] is used.
    weights_func : callable
        weights_func is called with nlags as argument to get the kernel
        weights. default are Bartlett weights

    Returns
    -------
    cov : ndarray, (k_vars, k_vars)
        HAC robust covariance matrix for parameter estimates
    bse : ndarray, (k_vars,)
        standard errors, this will be dropped


    Notes
    -----
    verified only for nlags=0, which is just White
    just guessing on correction factor, need reference

    options might change when other kernels besides Bartlett are available.

    '''
    xu = results.model.exog * results.resid[:, None]
    sigma = S_hac_simple(xu, nlags=nlags, weights_func=weights_func)

    cov_hac = _HCCM2(results, sigma)

    if use_correction:
        nobs, k_vars = results.model.exog.shape
        cov_hac *= nobs / float(nobs - k_vars)

    bse_hac = np.sqrt(np.diag(cov_hac))

    return cov_hac, bse_hac

#---------------------- use time lags corrected for groups
#the following were copied from a different experimental script,
#groupidx is tuple, observations assumed to be stacked by group member and
#sorted by time, equal number of periods is not required, but equal spacing is.
#I think this is pure within group HAC: apply HAC to each group member
#separately

def lagged_groups(x, lag, groupidx):
    '''
    assumes sorted by time, groupidx is tuple of start and end values
    not optimized, just to get a working version, loop over groups
    '''
    out0 = []
    out_lagged = []
    for l,u in groupidx:
        out0.append(x[l+lag:u])
        out_lagged.append(x[l:u-lag])

    #return out0, out_lagged
    return np.vstack(out0), np.vstack(out_lagged)



def S_nw_panel(xw, weights, groupidx):
    '''HAC for panel data

    no denominator nobs used

    no reference for this, just accounting for time indices
    '''
    nlags = len(weights)

    S = weights[0] * np.dot(xw.T, xw)  #weights just for completeness
    for lag in range(1, nlags+1):
        xw0, xwlag = lagged_groups(xw, lag, groupidx)
        s = np.dot(xw0.T, xwlag)
        S += weights[lag] * (s + s.T)
    return S


def cov_nw_panel(results, nlags, groupidx, use_correction=True):
    '''

    groupidx is list of tuple
    '''
    if nlags == 0: #so we can reproduce HC0 White
        weights = [1, 0]  #to avoid the scalar check in hac_nw
    else:
        weights = weights_bartlett(nlags)

    xw = (results.model.exog * results.resid[:,None])

    S_hac = S_nw_panel(xw, weights, groupidx)
    cov_hac = _HCCM2(results, S_hac)
    if use_correction:
        nobs, k_vars = results.model.exog.shape
        cov_hac *= nobs / float(nobs - k_vars)
    return cov_hac

#c = cov_nw_panel(results, 0, groupidx)
#assert_almost_equal(np.sqrt(np.diag(c)), results.HC0_se, decimal=14)

#------------------------
