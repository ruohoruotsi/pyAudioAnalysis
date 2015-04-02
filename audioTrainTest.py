import sys, numpy, time, os, glob, mlpy, cPickle, shutil, audioop, signal, csv, ntpath
import audioFeatureExtraction as aF
import audioBasicIO
from matplotlib.mlab import find
import matplotlib.pyplot as plt
import scipy.io as sIO
from scipy import linalg as la
from scipy.spatial import distance

def signal_handler(signal, frame):
        print 'You pressed Ctrl+C! - EXIT'
	os.system("stty -cbreak echo")
        sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

shortTermWindow = 0.050
shortTermStep = 0.050
eps = 0.00000001

class kNN:
	def __init__(self, X, Y, k):
		self.X = X
		self.Y = Y
		self.k = k
	def classify(self, testSample):
		nClasses = numpy.unique(self.Y).shape[0]
		YDist =  (distance.cdist(self.X, testSample.reshape(1, testSample.shape[0]), 'euclidean')).T
		iSort = numpy.argsort(YDist)
		P = numpy.zeros((nClasses,))
		for i in range(nClasses):
			P[i] = numpy.nonzero(self.Y[iSort[0][0:self.k]]==i)[0].shape[0] / float(self.k)
		return (numpy.argmax(P), P)

def classifierWrapper(classifier, classifierType, testSample):
	'''
	This function is used as a wrapper to pattern classification.
	ARGUMENTS:
		- classifier:		a classifier object of type mlpy.LibSvm or kNN (defined in this library)
		- classifierType:	"svm" or "knn"
		- testSample:		a feature vector (numpy array)
	RETURNS:
		- R:			class ID
		- P:			probability estimate

	EXAMPLE (for some audio signal stored in array x):
		import audioFeatureExtraction as aF
		import audioTrainTest as aT
		# load the classifier (here SVM, for kNN use loadKNNModel instead):
		[Classifier, MEAN, STD, classNames, mtWin, mtStep, stWin, stStep] = aT.loadSVModel(modelName)
		# mid-term feature extraction:
		[MidTermFeatures, _] = aF.mtFeatureExtraction(x, Fs, mtWin * Fs, mtStep * Fs, round(Fs*stWin), round(Fs*stStep));
		# feature normalization:
		curFV = (MidTermFeatures[:, i] - MEAN) / STD;
		# classification
		[Result, P] = classifierWrapper(Classifier, modelType, curFV)		
	'''
	R = -1; P = -1
	if classifierType == "knn":
		[R, P] = classifier.classify(testSample)
	elif classifierType == "svm":		
		R = classifier.pred(testSample)
		P = classifier.pred_probability(testSample)
	return [R, P]

def regressionWrapper(model, modelType, testSample):
	'''
	This function is used as a wrapper to pattern classification.
	ARGUMENTS:
		- model:		regression model
		- modelType:		"svm" or "knn" (TODO)
		- testSample:		a feature vector (numpy array)
	RETURNS:
		- R:			regression result (estimated value)

	EXAMPLE (for some audio signal stored in array x):
		TODO
	'''
	if modelType == "svm":
		return (model.pred(testSample))
#	elif classifierType == "knn":

	return None

def randSplitFeatures(features, partTrain):
	"""
	def randSplitFeatures(features):
	
	This function splits a feature set for training and testing.
	
	ARGUMENTS:
		- features: 		a list ([numOfClasses x 1]) whose elements containt numpy matrices of features.
					each matrix features[i] of class i is [numOfSamples x numOfDimensions] 
		- partTrain:		percentage 
	RETURNS:
		- featuresTrains:	a list of training data for each class
		- featuresTest:		a list of testing data for each class
	"""

	featuresTrain = []
	featuresTest = []
	for i,f in enumerate(features):
		[numOfSamples, numOfDims] = f.shape
		randperm = numpy.random.permutation(range(numOfSamples))
		nTrainSamples = int(round(partTrain * numOfSamples));
		featuresTrain.append(f[randperm[1:nTrainSamples]])
		featuresTest.append(f[randperm[nTrainSamples+1:-1]])
	return (featuresTrain, featuresTest)

def trainKNN(features, K):
	'''
	Train a kNN  classifier.
	ARGUMENTS:
		- features: 		a list ([numOfClasses x 1]) whose elements containt numpy matrices of features.
					each matrix features[i] of class i is [numOfSamples x numOfDimensions] 
		- K:			parameter K 
	RETURNS:
		- kNN:			the trained kNN variable

	'''
	[Xt, Yt] = listOfFeatures2Matrix(features)
	knn = kNN(Xt, Yt, K)
	return knn

def trainSVM(features, Cparam):
	'''
	Train a multi-class probabilitistic SVM classifier.
	Note: 	This function is simply a wrapper to the mlpy-LibSVM functionality for SVM training
		See function trainSVM_feature() to use a wrapper on both the feature extraction and the SVM training (and parameter tuning) processes.
	ARGUMENTS:
		- features: 		a list ([numOfClasses x 1]) whose elements containt numpy matrices of features.
					each matrix features[i] of class i is [numOfSamples x numOfDimensions] 
		- Cparam:		SVM parameter C (cost of constraints violation)
	RETURNS:
		- svm:			the trained SVM variable

	NOTE:	
		This function trains a linear-kernel SVM for a given C value. For a different kernel, other types of parameters should be provided.
		For example, gamma for a polynomial, rbf or sigmoid kernel. Furthermore, Nu should be provided for a nu_SVM classifier.
		See MLPY documentation for more details (http://mlpy.sourceforge.net/docs/3.4/svm.html)
	'''
	[X, Y] = listOfFeatures2Matrix(features)	
	svm = mlpy.LibSvm(svm_type='c_svc', kernel_type='linear', eps=0.0000001, C = Cparam, probability=True)
	svm.learn(X, Y)	
	return svm

def trainSVMregression(Features, Y, C):
	#svm = mlpy.LibSvm(svm_type='c_svc', kernel_type='linear', eps=0.0000001, C = C, probability=True)
	svm = mlpy.LibSvm(svm_type='epsilon_svr', kernel_type='linear', eps=0.001, C = C, probability=False)
	svm.learn(Features, Y)
	trainError = numpy.mean( numpy.abs( svm.pred(Features) - Y) )
	return svm, trainError 


def featureAndTrain(listOfDirs, mtWin, mtStep, stWin, stStep, classifierType, modelName, computeBEAT = False, perTrain = 0.90):
	'''
	This function is used as a wrapper to segment-based audio feature extraction and classifier training.
	ARGUMENTS:
		listOfDirs:		list of paths of directories. Each directory contains a signle audio class whose samples are stored in seperate WAV files.
		mtWin, mtStep:		mid-term window length and step
		stWin, stStep:		short-term window and step
		classifierType:		"svm" or "knn"
		modelName:		name of the model to be saved
	RETURNS: 
		None. Resulting classifier along with the respective model parameters are saved on files.
	'''
	# STEP A: Feature Extraction:
	[features, classNames, _] = aF.dirsWavFeatureExtraction(listOfDirs, mtWin, mtStep, stWin, stStep, computeBEAT = computeBEAT)

	if len(features)==0:
		print "trainSVM_feature ERROR: No data found in any input folder!"
		return

	numOfFeatures = features[0].shape[1]
	featureNames = [ "features" + str(d+1) for d in range(numOfFeatures)]

	writeTrainDataToARFF(modelName, features, classNames, featureNames);


	for i,f in enumerate(features):
		if len(f)==0:
			print "trainSVM_feature ERROR: " + listOfDirs[i] + " folder is empty or non-existing!"
			return

	# STEP B: Classifier Evaluation and Parameter Selection:
	if classifierType == "svm":
		classifierParams = numpy.array([0.001, 0.01,  0.5, 1.0, 5.0, 10.0])
	elif classifierType == "knn":
		classifierParams = numpy.array([1, 3, 5, 7, 9, 11, 13, 15]); 
		#classifierParams = numpy.array([51]); 

	# get optimal classifeir parameter:
	bestParam = evaluateClassifier(features, classNames, 100, classifierType, classifierParams, 0, perTrain)

	print "Selected params: {0:.5f}".format(bestParam)

	C = len(classNames)
	[featuresNorm, MEAN, STD] = normalizeFeatures(features)		# normalize features
	MEAN = MEAN.tolist(); STD = STD.tolist()
	featuresNew = featuresNorm 
	
	# STEP C: Save the classifier to file
	if classifierType == "svm":
		Classifier = trainSVM(featuresNew, bestParam)
		Classifier.save_model(modelName)
		fo = open(modelName + "MEANS", "wb")
		cPickle.dump(MEAN, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(STD,  fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(classNames,  fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(mtWin, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(mtStep, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(stWin, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(stStep, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(computeBEAT, fo, protocol = cPickle.HIGHEST_PROTOCOL)
	    	fo.close()
	elif classifierType == "knn":
		[X, Y] = listOfFeatures2Matrix(featuresNew)
		X = X.tolist(); Y = Y.tolist()
		fo = open(modelName, "wb")
		cPickle.dump(X, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(Y,  fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(MEAN, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(STD,  fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(classNames,  fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(bestParam,  fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(mtWin, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(mtStep, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(stWin, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(stStep, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		cPickle.dump(computeBEAT, fo, protocol = cPickle.HIGHEST_PROTOCOL)
	    	fo.close()

def featureAndTrainRegression(dirName, mtWin, mtStep, stWin, stStep, modelType, modelName, computeBEAT = False):
	'''
	This function is used as a wrapper to segment-based audio feature extraction and classifier training.
	ARGUMENTS:
		dirName:		path of directory containing the WAV files and Regression CSVs
		mtWin, mtStep:		mid-term window length and step
		stWin, stStep:		short-term window and step
		modelType:		"svm" or "knn"
		modelName:		name of the model to be saved
	RETURNS: 
		None. Resulting regression model along with the respective model parameters are saved on files.
	'''
	# STEP A: Feature Extraction:
	[features, _, fileNames] = aF.dirsWavFeatureExtraction([dirName], mtWin, mtStep, stWin, stStep, computeBEAT = computeBEAT)
	features = features[0]
	fileNames = [ntpath.basename(f) for f in fileNames[0]]

	# Read CSVs:
	CSVs = glob.glob(dirName + os.sep + "*.csv")
	regressionLabels = []
	regressionNames = []
	for c in CSVs:										# for each CSV
		curRegressionLabels = numpy.zeros((len(fileNames,)))				# read filenames, map to "fileNames" and append respective values in the regressionLabels
		with open(c, 'rb') as csvfile:
			CSVreader = csv.reader(csvfile, delimiter=',', quotechar='|')
			for row in CSVreader:
				if len(row)==2:
					if row[0]+".wav" in fileNames:
						index = fileNames.index(row[0]+".wav")
						curRegressionLabels[index] = float(row[1])
		regressionLabels.append(curRegressionLabels)					# curRegressionLabels is the list of values for the current regression problem
		regressionNames.append(ntpath.basename(c).replace(".csv",""))			# regression task name

	if len(features)==0:
		print "ERROR: No data found in any input folder!"
		return

	numOfFeatures = features.shape[1]

	# TODO: ARRF WRITE????
	# STEP B: Classifier Evaluation and Parameter Selection:
	if modelType == "svm":
		modelParams = numpy.array([0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0, 10.0])
#	elif modelType == "knn":
#		modelParams = numpy.array([1, 3, 5, 7, 9, 11, 13, 15]); 

	for iRegression, r in enumerate(regressionNames):
		# get optimal classifeir parameter:
		print "Regression task " + r
		bestParam = evaluateRegression(features, regressionLabels[iRegression], 100, modelType, modelParams)
		print "Selected params: {0:.5f}".format(bestParam)

		[featuresNorm, MEAN, STD] = normalizeFeatures([features])		# normalize features
	
		# STEP C: Save the model to file
		if modelType == "svm":
			Classifier, _ = trainSVMregression(featuresNorm[0], regressionLabels[iRegression], bestParam)
			Classifier.save_model(modelName + "_" + r)
			fo = open(modelName + "_" + r + "MEANS", "wb")
			cPickle.dump(MEAN, fo, protocol = cPickle.HIGHEST_PROTOCOL)
			cPickle.dump(STD,  fo, protocol = cPickle.HIGHEST_PROTOCOL)
			cPickle.dump(mtWin, fo, protocol = cPickle.HIGHEST_PROTOCOL)
			cPickle.dump(mtStep, fo, protocol = cPickle.HIGHEST_PROTOCOL)
			cPickle.dump(stWin, fo, protocol = cPickle.HIGHEST_PROTOCOL)
			cPickle.dump(stStep, fo, protocol = cPickle.HIGHEST_PROTOCOL)
			cPickle.dump(computeBEAT, fo, protocol = cPickle.HIGHEST_PROTOCOL)
		    	fo.close()
	#	elif classifierType == "knn":


def loadKNNModel(kNNModelName, isRegression = False):
	try:
		fo = open(kNNModelName, "rb")
	except IOError:
       		print "didn't find file"
        	return
    	try:
		X     = cPickle.load(fo)
		Y     = cPickle.load(fo)
		MEAN  = cPickle.load(fo)
		STD   = cPickle.load(fo)
		if not isRegression:
			classNames =  cPickle.load(fo)
		K     = cPickle.load(fo)
		mtWin = cPickle.load(fo)
		mtStep = cPickle.load(fo)
		stWin = cPickle.load(fo)
		stStep = cPickle.load(fo)
		computeBEAT = cPickle.load(fo)
    	except:
        	fo.close()
	fo.close()	

	X = numpy.array(X)
	Y = numpy.array(Y)
	MEAN = numpy.array(MEAN)
	STD = numpy.array(STD)

	Classifier = kNN(X, Y, K) # Note: a direct call to the kNN constructor is used here, since the 
       
	if isRegression:
		return(Classifier, MEAN, STD, mtWin, mtStep, stWin, stStep, computeBEAT);	
	else:
		return(Classifier, MEAN, STD, classNames, mtWin, mtStep, stWin, stStep, computeBEAT);

def loadSVModel(SVMmodelName, isRegression = False):
	'''
	This function loads an SVM model either for classification or training.
	ARGMUMENTS:
		- SVMmodelName: 	the path of the model to be loaded
		- isRegression:		a flag indigating whereas this model is regression or not
	'''
	try:
		fo = open(SVMmodelName+"MEANS", "rb")
	except IOError:
       		print "Load SVM Model: Didn't find file"
        	return
    	try:
		MEAN     = cPickle.load(fo)
		STD      = cPickle.load(fo)
		if not isRegression:
			classNames =  cPickle.load(fo)
		mtWin = cPickle.load(fo)
		mtStep = cPickle.load(fo)
		stWin = cPickle.load(fo)
		stStep = cPickle.load(fo)
		computeBEAT = cPickle.load(fo)		

    	except:
        	fo.close()
	fo.close()	

	MEAN = numpy.array(MEAN)
	STD  = numpy.array(STD)

	COEFF = []
	SVM = mlpy.LibSvm.load_model(SVMmodelName)

	if isRegression:
		return(SVM, MEAN, STD, mtWin, mtStep, stWin, stStep, computeBEAT);				
	else:
		return(SVM, MEAN, STD, classNames, mtWin, mtStep, stWin, stStep, computeBEAT);				

def evaluateClassifier(features, ClassNames, nExp, ClassifierName, Params, parameterMode, perTrain = 0.90):
	'''
	ARGUMENTS:
		features: 	a list ([numOfClasses x 1]) whose elements containt numpy matrices of features.
				each matrix features[i] of class i is [numOfSamples x numOfDimensions] 
		ClassNames:	list of class names (strings)
		nExp:		number of cross-validation experiments
		ClassifierName: svm or knn
		Params:		list of classifier parameters (for parameter tuning during cross-validation)
		parameterMode:	0: choose parameters that lead to maximum overall classification ACCURACY
				1: choose parameters that lead to maximum overall F1 MEASURE
	RETURNS:
	 	bestParam:	the value of the input parameter that optimizes the selected performance measure		
	'''

	# feature normalization:
	(featuresNorm, MEAN, STD) = normalizeFeatures(features)
	#featuresNorm = features;
	nClasses = len(features)
	CAll = []; acAll = []; F1All = []	
	PrecisionClassesAll = []; RecallClassesAll = []; ClassesAll = []; F1ClassesAll = []
	CMsAll = []

	for Ci, C in enumerate(Params):				# for each param value		
				CM = numpy.zeros((nClasses, nClasses))
				for e in range(nExp):		# for each cross-validation iteration:
					# split features:
					featuresTrain, featuresTest = randSplitFeatures(featuresNorm, perTrain)
					# train multi-class svms:
					if ClassifierName=="svm":
						Classifier = trainSVM(featuresTrain, C)
					elif ClassifierName=="knn":
						Classifier = trainKNN(featuresTrain, C)

					CMt = numpy.zeros((nClasses, nClasses))
					for c1 in range(nClasses):
						#Results = Classifier.pred(featuresTest[c1])
						nTestSamples = len(featuresTest[c1])
						Results = numpy.zeros((nTestSamples,1))
						for ss in range(nTestSamples):
							[Results[ss], _] = classifierWrapper(Classifier, ClassifierName, featuresTest[c1][ss])
						for c2 in range(nClasses):
							CMt[c1][c2] = float(len(numpy.nonzero(Results==c2)[0]))
					CM = CM + CMt
				CM = CM + 0.0000000010
				Rec = numpy.zeros((CM.shape[0],))
				Pre = numpy.zeros((CM.shape[0],))

				for ci in range(CM.shape[0]):
					Rec[ci] = CM[ci,ci] / numpy.sum(CM[ci,:]);
					Pre[ci] = CM[ci,ci] / numpy.sum(CM[:,ci]);
				PrecisionClassesAll.append(Pre)
				RecallClassesAll.append(Rec)
				F1 = 2 * Rec * Pre / (Rec + Pre)
				F1ClassesAll.append(F1)
				acAll.append(numpy.sum(numpy.diagonal(CM)) / numpy.sum(CM))

				CMsAll.append(CM)
				F1All.append(numpy.mean(F1))
				# print "{0:6.4f}{1:6.4f}{2:6.1f}{3:6.1f}".format(nu, g, 100.0*acAll[-1], 100.0*F1All[-1])

	print ("\t\t"),
	for i,c in enumerate(ClassNames): 
		if i==len(ClassNames)-1: print "{0:s}\t\t".format(c),  
		else: print "{0:s}\t\t\t".format(c), 
	print ("OVERALL")
	print ("\tC"),
	for c in ClassNames: print "\tPRE\tREC\tF1", 
	print "\t{0:s}\t{1:s}".format("ACC","F1")
	bestAcInd = numpy.argmax(acAll)
	bestF1Ind = numpy.argmax(F1All)
	for i in range(len(PrecisionClassesAll)):
		print "\t{0:.3f}".format(Params[i]),
		for c in range(len(PrecisionClassesAll[i])):
			print "\t{0:.1f}\t{1:.1f}\t{2:.1f}".format(100.0*PrecisionClassesAll[i][c], 100.0*RecallClassesAll[i][c], 100.0*F1ClassesAll[i][c]), 
		print "\t{0:.1f}\t{1:.1f}".format(100.0*acAll[i], 100.0*F1All[i]),
		if i == bestF1Ind: print "\t best F1", 
		if i == bestAcInd: print "\t best Acc",
 		print

	if parameterMode==0:	# keep parameters that maximize overall classification accuracy:
		print "Confusion Matrix:"
		printConfusionMatrix(CMsAll[bestAcInd], ClassNames)
		return Params[bestAcInd]
	elif parameterMode==1:  # keep parameters that maximize overall F1 measure:
		print "Confusion Matrix:"
		printConfusionMatrix(CMsAll[bestF1Ind], ClassNames)
		return Params[bestF1Ind]


def evaluateRegression(features, labels, nExp, MethodName, Params):
	'''
	ARGUMENTS:
		features: 	numpy matrices of features [numOfSamples x numOfDimensions] 
		labels:		list of sample labels
		nExp:		number of cross-validation experiments
		MethodName:	svm or knn
		Params:		list of classifier params to be evaluated
	RETURNS:
	 	bestParam:	the value of the input parameter that optimizes the selected performance measure		
	'''

	# feature normalization:
	(featuresNorm, MEAN, STD) = normalizeFeatures([features])
	featuresNorm = featuresNorm[0]
	nSamples = labels.shape[0]
	partTrain = 0.9
	ErrorsAll = []
	ErrorsTrainAll = [];
	ErrorsBaselineAll = [];
	for Ci, C in enumerate(Params):				# for each param value
				Errors = []
				ErrorsTrain = []
				ErrorsBaseline = []
				for e in range(nExp):		# for each cross-validation iteration:
					# split features:
					randperm = numpy.random.permutation(range(nSamples))
					nTrain = int(round(partTrain * nSamples))
					featuresTrain = [featuresNorm[randperm[i]] for i in range(nTrain)]
					featuresTest = [featuresNorm[randperm[i+nTrain]] for i in range(nSamples - nTrain)]
					labelsTrain = [labels[randperm[i]] for i in range(nTrain)]
					labelsTest  = [labels[randperm[i+nTrain]] for i in range(nSamples - nTrain)]

					# train multi-class svms:
					if MethodName=="svm":
						featuresTrain = numpy.matrix(featuresTrain)
						[Classifier, trainError] = trainSVMregression(featuresTrain, labelsTrain, C)
# TODO KNN
#					elif ClassifierName=="knn":
#						Classifier = trainKNN(featuresTrain, C)

					ErrorTest = []
					ErrorTestBaseline = []
					for itest, fTest in enumerate(featuresTest):
						R = regressionWrapper(Classifier, MethodName, fTest)
						Rbaseline = numpy.mean(labelsTrain)
						ErrorTest.append((R - labelsTest[itest])*(R - labelsTest[itest]));
						ErrorTestBaseline.append((Rbaseline - labelsTest[itest])*(Rbaseline - labelsTest[itest]));					
					Error = numpy.array(ErrorTest).mean()
					ErrorBaseline = numpy.array(ErrorTestBaseline).mean()
					Errors.append(Error)
					ErrorsTrain.append(trainError)
					ErrorsBaseline.append(ErrorBaseline)
				ErrorsAll.append(numpy.array(Errors).mean())
				ErrorsTrainAll.append(numpy.array(ErrorsTrain).mean())
				ErrorsBaselineAll.append(numpy.array(ErrorsBaseline).mean())

	bestInd = numpy.argmin(ErrorsAll)

	print "{0:s}\t\t{1:s}\t\t{2:s}\t\t{3:s}".format("Param","MSE", "T-MSE","R-MSE")
	for i in range(len(ErrorsAll)):
		print "{0:.4f}\t\t{1:.2f}\t\t{2:.2f}\t\t{3:.2f}".format(Params[i], ErrorsAll[i], ErrorsTrainAll[i], ErrorsBaselineAll[i]),
		if i == bestInd: print "\t\t best", 
		print 
	return Params[bestInd]


def printConfusionMatrix(CM, ClassNames):
	'''
	This function prints a confusion matrix for a particular classification task.
	ARGUMENTS:
		CM:		a 2-D numpy array of the confusion matrix 
				(CM[i,j] is the number of times a sample from class i was classified in class j)
		ClassNames:	a list that contains the names of the classes
	'''

	if CM.shape[0] != len(ClassNames):
		print "printConfusionMatrix: Wrong argument sizes\n"
		return

	for c in ClassNames: 
		if len(c)>4: 
			c = c[0:3]
		print "\t{0:s}".format(c),
	print

	for i, c in enumerate(ClassNames):
		if len(c)>4: c = c[0:3]
		print "{0:s}".format(c),
		for j in range(len(ClassNames)):
			print "\t{0:.1f}".format(100.0*CM[i][j] / numpy.sum(CM)),
		print

def normalizeFeatures(features):
	'''
	This function normalizes a feature set to 0-mean and 1-std.
	Used in most classifier trainning cases.

	ARGUMENTS:
		- features:	list of feature matrices (each one of them is a numpy matrix)
	RETURNS:
		- featuresNorm:	list of NORMALIZED feature matrices
		- MEAN:		mean vector
		- STD:		std vector
	'''
	X = numpy.array([])
	
	for count,f in enumerate(features):
		if f.shape[0]>0:
			if count==0:
				X = f
			else:
				X = numpy.vstack((X, f))
			count += 1
	
	MEAN = numpy.mean(X, axis = 0)
	STD  = numpy.std( X, axis = 0)

	featuresNorm = []
	for f in features:
		ft = f.copy()
		for nSamples in range(f.shape[0]):
			ft[nSamples,:] = (ft[nSamples,:] - MEAN) / STD	
		featuresNorm.append(ft)
	return (featuresNorm, MEAN, STD)

def listOfFeatures2Matrix(features):
	'''
	listOfFeatures2Matrix(features)
	
	This function takes a list of feature matrices as argument and returns a single concatenated feature matrix and the respective class labels.

	ARGUMENTS:
		- features:		a list of feature matrices

	RETURNS:
		- X:			a concatenated matrix of features
		- Y:			a vector of class indeces	
	'''

	X = numpy.array([])
	Y = numpy.array([])
	for i,f in enumerate(features):
		if i==0:
			X = f
			Y = i * numpy.ones((len(f), 1))
		else:
			X = numpy.vstack((X, f))
			Y = numpy.append(Y, i * numpy.ones((len(f), 1)))
	return (X, Y)


def pcaDimRed(features, nDims):
	[X, Y] = listOfFeatures2Matrix(features)
	pca = mlpy.PCA(method='cov')
	pca.learn(X)
	coeff = pca.coeff()
	coeff = coeff[:,0:nDims]

	featuresNew = []
	for f in features:
		ft = f.copy()
#		ft = pca.transform(ft, k=nDims)
		ft = numpy.dot(f, coeff)
		featuresNew.append(ft)

	return (featuresNew, coeff)

def fileClassification(inputFile, modelName, modelType):
	# Load classifier:

	if not os.path.isfile(modelName):
		print "fileClassification: input modelName not found!"
		return (-1,-1, -1)

	if not os.path.isfile(inputFile):
		print "fileClassification: wav file not found!"
		return (-1,-1, -1)


	if modelType=='svm':
		[Classifier, MEAN, STD, classNames, mtWin, mtStep, stWin, stStep, computeBEAT] = loadSVModel(modelName)
	elif modelType=='knn':
		[Classifier, MEAN, STD, classNames, mtWin, mtStep, stWin, stStep, computeBEAT] = loadKNNModel(modelName)
			
	[Fs, x] = audioBasicIO.readAudioFile(inputFile)		# read audio file and convert to mono
	x = audioBasicIO.stereo2mono(x);
	# feature extraction:
	[MidTermFeatures, s] = aF.mtFeatureExtraction(x, Fs, mtWin * Fs, mtStep * Fs, round(Fs*stWin), round(Fs*stStep));
	MidTermFeatures = MidTermFeatures.mean(axis=1)		# long term averaging of mid-term statistics
	if computeBEAT:
		[beat, beatConf] = aF.beatExtraction(s, stStep)
		MidTermFeatures = numpy.append(MidTermFeatures, beat);
		MidTermFeatures = numpy.append(MidTermFeatures, beatConf);
	curFV = (MidTermFeatures - MEAN) / STD;			# normalization

	[Result, P] = classifierWrapper(Classifier, modelType, curFV)	# classification
	return Result, P, classNames

def fileRegression(inputFile, modelName, modelType):
	# Load classifier:

	if not os.path.isfile(inputFile):
		print "fileClassification: wav file not found!"
		return (-1,-1, -1)

	regressionModels = glob.glob(modelName + "*")
	regressionModels2 = []
	for r in regressionModels:
		if r[-5::] != "MEANS":
			regressionModels2.append(r)
	regressionModels = regressionModels2
	regressionNames = []
	for r in regressionModels:
		regressionNames.append(r[r.rfind("_")+1::])

	# FEATURE EXTRACTION
	# LOAD ONLY THE FIRST MODEL (for mtWin, etc)
	if modelType=='svm':
		[_, _, _, mtWin, mtStep, stWin, stStep, computeBEAT] = loadSVModel(regressionModels[0], True)
	elif modelType=='knn':
		[_, _, _, mtWin, mtStep, stWin, stStep, computeBEAT] = loadKNNModel(regressionModels[0], True)

	[Fs, x] = audioBasicIO.readAudioFile(inputFile)		# read audio file and convert to mono
	x = audioBasicIO.stereo2mono(x);
	# feature extraction:
	[MidTermFeatures, s] = aF.mtFeatureExtraction(x, Fs, mtWin * Fs, mtStep * Fs, round(Fs*stWin), round(Fs*stStep));
	MidTermFeatures = MidTermFeatures.mean(axis=1)		# long term averaging of mid-term statistics
	if computeBEAT:
		[beat, beatConf] = aF.beatExtraction(s, stStep)
		MidTermFeatures = numpy.append(MidTermFeatures, beat);
		MidTermFeatures = numpy.append(MidTermFeatures, beatConf);

	# REGRESSION
	R = []
	for ir, r in enumerate(regressionModels):
		if not os.path.isfile(r):
			print "fileClassification: input modelName not found!"
			return (-1,-1, -1)
		if modelType=='svm':
			[Model, MEAN, STD, mtWin, mtStep, stWin, stStep, computeBEAT] = loadSVModel(r, True)
		elif modelType=='knn':
			[Model, MEAN, STD, mtWin, mtStep, stWin, stStep, computeBEAT] = loadKNNModel(r, True)			
		curFV = (MidTermFeatures - MEAN) / STD;			# normalization
		R.append(regressionWrapper(Model, modelType, curFV))	# classification
	return R, regressionNames


def lda(data,labels,redDim):

    # Centre data
    data -= data.mean(axis=0)
    nData = numpy.shape(data)[0]
    nDim = numpy.shape(data)[1]
    print nData, nDim
    Sw = numpy.zeros((nDim,nDim))
    Sb = numpy.zeros((nDim,nDim))
    
    C = numpy.cov((data.T))

    # Loop over classes    
    classes = numpy.unique(labels)
    for i in range(len(classes)):
        # Find relevant datapoints
        indices = (numpy.where(labels==classes[i]))
        d = numpy.squeeze(data[indices,:])
        classcov = numpy.cov((d.T))
        Sw += float(numpy.shape(indices)[0])/nData * classcov
        
    Sb = C - Sw
    # Now solve for W
    # Compute eigenvalues, eigenvectors and sort into order
    #evals,evecs = linalg.eig(dot(linalg.pinv(Sw),sqrt(Sb)))
    evals,evecs = la.eig(Sw,Sb)
    indices = numpy.argsort(evals)
    indices = indices[::-1]
    evecs = evecs[:,indices]
    evals = evals[indices]
    w = evecs[:,:redDim]
    #print evals, w

    newData = numpy.dot(data,w)
    #for i in range(newData.shape[0]):
    #	plt.text(newData[i,0],newData[i,1],str(labels[i]))

    #plt.xlim([newData[:,0].min(), newData[:,0].max()])
    #plt.ylim([newData[:,1].min(), newData[:,1].max()])
    #plt.show()
    return newData,w

def writeTrainDataToARFF(modelName, features, classNames, featureNames):
	f = open(modelName + ".arff", 'w')
	f.write('@RELATION ' + modelName + '\n');
	for fn in featureNames:
		f.write('@ATTRIBUTE ' + fn + ' NUMERIC\n')
	f.write('@ATTRIBUTE class {')
	for c in range(len(classNames)-1):
		f.write(classNames[c] + ',')
	f.write(classNames[-1] + '}\n\n')
	f.write('@DATA\n')
	for c, fe in enumerate(features):
		for i in range(fe.shape[0]):
			for j in range(fe.shape[1]):
				f.write("{0:f},".format(fe[i,j]))
			f.write(classNames[c]+"\n")
	f.close()


def trainSpeakerModelsScript():
	'''
	This script is used to train the speaker-related models (NOTE: data paths are hard-coded and NOT included in the library, the models are, however included)
 		import audioTrainTest as aT
		aT.trainSpeakerModelsScript()

	'''
	mtWin = 2.0;  mtStep = 2.0; stWin = 0.020; stStep = 0.020;

	dirName = "DIARIZATION_ALL/all"
	listOfDirs  = [ os.path.join(dirName, name) for name in os.listdir(dirName) if os.path.isdir(os.path.join(dirName, name)) ]
	featureAndTrain(listOfDirs, mtWin, mtStep, stWin, stStep, "knn", "data/knnSpeakerAll", computeBEAT = False, perTrain = 0.50)

	dirName = "DIARIZATION_ALL/female_male"
	listOfDirs  = [ os.path.join(dirName, name) for name in os.listdir(dirName) if os.path.isdir(os.path.join(dirName, name)) ]
	featureAndTrain(listOfDirs, mtWin, mtStep, stWin, stStep, "knn", "data/knnSpeakerFemaleMale", computeBEAT = False, perTrain = 0.50)


def main(argv):
	return 0
	
if __name__ == '__main__':
	main(sys.argv)
