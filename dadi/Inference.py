"""
Comparison and optimization of model spectra to data.
"""
import numpy

import SFS, Misc

counter = 0
out_of_bounds_val = -1e8
def object_func(params, data, model_func, pts, 
                lower_bound=None, upper_bound=None, fold=False,
                verbose=0, multinom=True):
    global counter
    counter += 1

    data = numpy.ma.asarray(data)

    if (lower_bound is not None and numpy.any(params < lower_bound)) or\
       (upper_bound is not None and numpy.any(params > upper_bound)):
        ll = out_of_bounds_val
    else:
        ns = list(numpy.asarray(data.shape) - 1)
        sfs = model_func(*([params] + [ns] + [pts]))
        if fold:
            sfs = SFS.fold_sfs(sfs)
            data = SFS.fold_sfs(data)
        if multinom:
            ll = ll_multinom(sfs, data)
        else:
            ll = ll(sfs, data)

    if numpy.isnan(ll):
        ll = out_of_bounds_val

    if (verbose > 0) and (counter % verbose == 0):
        param_str = 'array([%s])' % (', '.join(['%- 12g'%v for v in params]))
        print '%-8i, %-12g, %s' % (counter, ll, param_str)
        Misc.delayed_flush()

    return -ll

def object_func_log(log_params, *args, **kwargs):
    return object_func(numpy.exp(log_params), *args, **kwargs)

def optimize_log(p0, data, model_func, pts, lower_bound=None, upper_bound=None,
                 fold=False, verbose=0, flush_delay=0.5, epsilon=1e-4, 
                 gtol=1e-5, multinom=True, maxiter=None, full_output=False):
    import scipy.optimize

    old_flush_delay = Misc.default_flush_delay
    Misc.default_flush_delay = flush_delay

    args = (data, model_func, pts, lower_bound, upper_bound, fold, verbose,
            multinom)

    outputs = scipy.optimize.fmin_bfgs(object_func_log, 
                                       numpy.log(p0), epsilon=epsilon,
                                       args = args, gtol=gtol, 
                                       full_output=True,
                                       disp=False,
                                       maxiter=maxiter)
    xopt, fopt, gopt, Bopt, func_calls, grad_calls, warnflag = outputs

    Misc.default_flush_delay = old_flush_delay

    if not full_output:
        return numpy.exp(xopt)
    else:
        return numpy.exp(xopt), fopt, gopt, Bopt, func_calls, grad_calls,\
                warnflag

# Create a version of the gamma function that will work with masked arrays.
from scipy.special import gammaln
if hasattr(numpy.ma, 'masked_unary_operation'):
    _gammaln_m = numpy.ma.masked_unary_operation(gammaln)
else:
    _gammaln_m = gammaln
def minus_ll(model, data):
    """
    The negative of the log-likelihood of the data given the model sfs.
    """
    return -ll(model, data)

def ll(model, data):
    """
    The log-likelihood of the data given the model sfs.

    Evaluate the log-likelihood of the data given the model. This is based on
    Poisson statistics, where the probability of observing k entries in a cell
    given that the mean number is given by the model is 
    P(k) = exp(-model) * model**k / k!

    Note: If either the model or the data is a masked array, the return ll will
          ignore any elements that are masked in *either* the model or the data.
    """
    ll_arr = ll_per_bin(model, data)
    return ll_arr.sum()

def ll_per_bin(model, data):
    """
    The Poisson log-likelihood of each entry in the data given the model sfs.
    """
    model = numpy.ma.asarray(model)
    data = numpy.ma.asarray(data)
    return -model + data*numpy.log(model) - _gammaln_m(data + 1)

def ll_multinom_per_bin(model, data):
    """
    Mutlinomial log-likelihood of each entry in the data given the model.

    Scales the model sfs to have the optimal theta for comparison with the data.
    """
    theta_opt = optimal_sfs_scaling(model, data)
    return ll_per_bin(theta_opt*model, data)

def ll_multinom(model, data):
    """
    Log-likelihood of the data given the model, with optimal rescaling.

    Evaluate the log-likelihood of the data given the model. This is based on
    Poisson statistics, where the probability of observing k entries in a cell
    given that the mean number is given by the model is 
    P(k) = exp(-model) * model**k / k!

    model is optimally scaled to maximize ll before calculation.

    Note: If either the model or the data is a masked array, the return ll will
          ignore any elements that are masked in *either* the model or the data.
    """
    ll_arr = ll_multinom_per_bin(model, data)
    return ll_arr.sum()

def minus_ll_multinom(model, data):
    """
    The negative of the log-likelihood of the data given the model sfs.

    Return a double that is -(log-likelihood)
    """
    return -ll_multinom(model, data)

def linear_Poisson_residual(model, data, mask=None):
    """
    Return the Poisson residuals, (model - data)/sqrt(model), of model and data.

    mask sets the level in model below which the returned residual array is
    masked. The default of 0 excludes values where the residuals are not 
    defined.

    In the limit that the mean of the Poisson distribution is large, these
    residuals are normally distributed. (If the mean is small, the Anscombe
    residuals are better.)
    """
    resid = (model - data)/numpy.sqrt(model)
    if mask is not None:
        tomask = numpy.logical_and(model <= mask, data <= mask)
        resid = numpy.ma.masked_where(tomask, resid)
    return resid

def Anscombe_Poisson_residual(model, data, mask=None):
    """
    Return the Anscombe Poisson residuals between model and data.

    mask sets the level in model below which the returned residual array is
    masked. This excludes very small values where the residuals are not normal.
    1e-2 seems to be a good default for the NIEHS human data. (model = 1e-2,
    data = 0, yields a residual of ~1.5.)

    Residuals defined in this manner are more normally distributed than the
    linear residuals when the mean is small. See this reference below for
    justification: Pierce DA and Schafer DW, "Residuals in generalized linear
    models" Journal of the American Statistical Association, 81(396)977-986
    (1986).

    Note that I tried implementing the "adjusted deviance" residuals, but they
    always looked like crap for the cases where the data was 0.
    """
    # Because my data have often been projected downward or averaged over many
    # iterations, it appears better to apply the same transformation to the data
    # and the model.
    datatrans = data**(2./3)-data**(-1./3)/9
    modeltrans = model**(2./3)-model**(-1./3)/9
    resid = 1.5*(datatrans - modeltrans)/model**(1./6)
    if mask is not None:
        tomask = numpy.logical_and(model <= mask, data <= mask)
        tomask = numpy.logical_or(tomask, data == 0)
        resid = numpy.ma.masked_where(tomask, resid)
    # It makes more sense to me to have a minus sign here... So when the
    # model is high, the residual is positive. This is opposite of the
    # Pierce and Schafner convention.
    return -resid